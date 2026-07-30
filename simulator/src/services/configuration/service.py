"""The configuration service — the one way to read a setting.

    from src.services.configuration.service import configuration

    configuration.get("shop_base_url")

Every setting in the simulator is read through `configuration.get(key)`, whether
it is a connection string fixed at deploy time or a knob a portal moved a second
ago. Values resolve through three layers, first hit wins:

1. **Dynamic** — a row in the activity database, for the keys in `TUNABLES`.
   Changeable while the app runs; this is what a portal writes.
2. **Static** — the environment, via `.env` or a real variable. The deploy's
   answer. Changing one is a restart.
3. **Default** — the value shipped in `src/config.py`. What the lab does out of
   the box, with no environment and no database.

Layers 2 and 3 are both `src/config.py`'s job — pydantic-settings collapses them
into one attribute — so `get()` reads them as one lookup. They are told apart
only in `describe()`, where the difference is the whole question: an operator
needs to know whether clearing an override lands on a deployment choice or on the
shipped value.

**`get` is synchronous, and that is the point.** Configuration is read where no
`await` can reach: `@service.every(...)` binds a schedule at import, `include(
enabled=)` decides wiring before the loop exists, `Service(max_slots=)` sizes a
pool at class scope. An async getter would leave those sites reading
`src/config.py` directly — and one interface that covers most reads is just two
interfaces wearing one name. So `get` answers from an in-process snapshot and
never does I/O, the same shape the runtime uses for its switch registry.

The snapshot is kept current by `refresh()`, which each service's lifespan awaits
once at boot, and by a background reload scheduled off a stale read. A caller
therefore sees a change within the TTL rather than instantly — that is what the
snapshot buys, and why the TTL is a minute rather than an hour.

**Without a source it is static-only**, which is exactly right for a unit test: no
database, no network, and every key answering with the value the lab ships.
`use()` supplies the source; nothing else needs to know whether one is set.
"""

import asyncio
import json
import logging
import time
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.services.configuration.models import SimulatorSetting

log = logging.getLogger("simulator.configuration")

CACHE_TTL_SECONDS = 60.0

TUNABLES: dict[str, Any] = {
    "base_arrivals_per_minute": float,
    "market_mix": dict[str, float],
    "max_arrivals_per_tick": int,
    "fast": bool,
}
"""What may be changed at runtime, and the shape each value must have.

Deliberately short. A knob belongs here only if changing it mid-run is meaningful
AND safe, which rules out more than it admits:

* `tick_seconds` and the three `*_interval` values are bound by
  `@service.every(...)` when the module is imported. A new value would be stored,
  reported as applied, and silently ignored — worse than no knob at all.
* The six `*_enabled` flags feed `App.include(enabled=)`, which decides whether a
  flow is *constructed*. That is wiring, not configuration. The runtime's switch
  registry is the mechanism for pausing a live flow.
* `journey_slots` sizes the browser pool at lifespan, and `debug_show_browser` is
  fixed when Chromium launches — changing either would apply to nothing, or to new
  sessions only, which is the confusing half-way case.
* `arrival_timezone` is not independently changeable: it must agree with the
  shop's PS_TIMEZONE and Matomo's site timezone, both set at provisioning. Moving
  one of the three at runtime desynchronises the company's clock silently.

Every other key still comes through `get()`; being absent here only means the
database cannot override it.

`fast` earns its place because the journey reads it per run, so a change applies
to the next customer and nothing already in flight.
"""


def validate(key: str, value: Any) -> Any:
    """Coerce a value to the tunable's declared shape, or raise.

    Validation happens on the way IN, so a malformed override cannot be stored
    and then break a tick later, somewhere with no context about who set it.
    """
    if key not in TUNABLES:
        raise KeyError(f"{key!r} is not runtime-tunable; tunables: {sorted(TUNABLES)}")
    try:
        return TypeAdapter(TUNABLES[key]).validate_python(value)
    except ValidationError as exc:
        raise ValueError(f"{key!r} rejected: {exc.errors()[0]['msg']}") from exc


def _static(key: str) -> Any:
    """The environment's value, or the shipped default — one attribute for both."""
    if not hasattr(settings, key):
        raise KeyError(f"unknown setting {key!r}")
    return getattr(settings, key)


def _describe(key: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """One tunable's effective value and the layer that supplied it.

    `static` is what clearing the override would restore; `default` is what ships
    in code. The two differ exactly when the environment sets the key, and a UI
    needs both to say truthfully what its reset button does — "back to 3/min"
    reads very differently from "back to whatever this deployment configured".
    """
    static = _static(key)
    if key in overrides:
        source = "database"
    elif key in settings.model_fields_set:
        # pydantic-settings records which fields an env var or .env line supplied,
        # which is the only way to tell a deployment's choice from the shipped
        # value — both arrive as the same attribute.
        source = "environment"
    else:
        source = "default"
    return {
        "value": overrides.get(key, static),
        "source": source,
        "static": static,
        "default": type(settings).model_fields[key].default,
    }


class Configuration:
    """Effective configuration: dynamic over static over default."""

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._overrides: dict[str, Any] = {}
        self._loaded_at: float | None = None
        self._reloading = False
        self._tasks: set[asyncio.Task[None]] = set()

    def use(self, sessionmaker: async_sessionmaker[AsyncSession] | None) -> None:
        """Point at the database that holds the overrides, or `None` to detach.

        Called once during wiring. Until it is, every key answers from the static
        layer and nothing touches a database — which is what makes the unit tests
        hermetic without stubbing anything. Detaching drops the snapshot with it,
        so the next read is back to the static layer rather than serving values
        from a database that is no longer attached.
        """
        self._sessionmaker = sessionmaker
        if sessionmaker is None:
            self._overrides = {}
            self._loaded_at = None

    @property
    def has_database(self) -> bool:
        """Whether overrides can be resolved at all, or this is static-only.

        Worth surfacing on a health check: static-only is the correct state for a
        test and a silent misconfiguration anywhere else — a portal would appear
        to save and never take effect.
        """
        return self._sessionmaker is not None

    def get(self, key: str) -> Any:
        """The effective value of any setting. Never does I/O; never blocks.

        A key that is not tunable resolves straight from the static layer —
        nothing could override it, so asking costs an attribute lookup.
        """
        if key not in TUNABLES:
            return _static(key)
        self._reload_if_stale()
        return self._overrides.get(key, _static(key))

    async def refresh(self) -> None:
        """Reload the overrides now, and wait for it.

        Awaited by each service's lifespan at boot so the first tick already sees
        the stored values rather than running one pass on the defaults.
        """
        if self._sessionmaker is not None:
            await self._load(self._sessionmaker)

    async def describe(self) -> dict[str, dict[str, Any]]:
        """Every tunable, its effective value, and which layer supplied it.

        Reloads first, unlike `get`: this answers "did my change apply?", so a
        snapshot up to a minute old would be answering a different question.
        """
        await self.refresh()
        return {key: _describe(key, self._overrides) for key in sorted(TUNABLES)}

    async def set(self, key: str, value: Any) -> Any:
        """Store an override. Returns the value as stored."""
        sessionmaker = self._require_source()
        coerced = validate(key, value)
        # Round-trip through JSON so what is cached is what a later read gets:
        # a tuple or a Decimal would come back from JSONB as something else.
        stored = json.loads(json.dumps(coerced))

        async with sessionmaker() as session:
            await session.execute(
                insert(SimulatorSetting)
                .values(key=key, value=stored)
                .on_conflict_do_update(
                    index_elements=[SimulatorSetting.key],
                    set_={"value": stored, "updated_at": func.now()},
                )
            )
            await session.commit()

        await self._load(sessionmaker)
        log.info("setting %s = %s", key, stored)
        return stored

    async def clear(self, key: str) -> None:
        """Drop an override, falling back to the layer below."""
        if key not in TUNABLES:
            raise KeyError(f"{key!r} is not runtime-tunable")
        sessionmaker = self._require_source()
        async with sessionmaker() as session:
            row = await session.get(SimulatorSetting, key)
            if row is not None:
                await session.delete(row)
                await session.commit()

        await self._load(sessionmaker)
        log.info("setting %s cleared — back to %s", key, _static(key))

    def _require_source(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            raise RuntimeError(
                "configuration has no database; call use(sessionmaker) before writing"
            )
        return self._sessionmaker

    async def _load(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        async with sessionmaker() as session:
            rows = (await session.execute(select(SimulatorSetting))).scalars().all()

        overrides: dict[str, Any] = {}
        for row in rows:
            try:
                overrides[row.key] = validate(row.key, row.value)
            except (KeyError, ValueError) as exc:
                # A stored value that no longer validates — a renamed tunable, or a
                # hand-edited row. Fall back to the layer below rather than take
                # the whole tick down with it.
                log.warning("ignoring stored setting %s: %s", row.key, exc)

        self._overrides = overrides
        self._loaded_at = time.monotonic()

    def _reload_if_stale(self) -> None:
        """Schedule a reload if the snapshot has aged out. Returns immediately.

        `get` is synchronous and on the arrivals hot path, so it hands the reload
        to the loop and answers from what it already has. The cost is that a
        change lands one read late; the alternative is a database round trip per
        read, which is the thing the snapshot exists to avoid.
        """
        if self._sessionmaker is None or self._reloading:
            return
        if (
            self._loaded_at is not None
            and time.monotonic() - self._loaded_at < self._ttl
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Read at import time, before the app runs. The static layer is the
            # only correct answer there anyway — nothing in TUNABLES is read at
            # import, by construction.
            return

        self._reloading = True
        task = loop.create_task(self._reload())
        # Hold a reference: the loop only keeps a weak one, so an unreferenced
        # task can be collected mid-flight.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _reload(self) -> None:
        try:
            await self.refresh()
        except Exception:
            # Never let a database blip stop the simulator: the last known values
            # stay in force and the next stale read tries again.
            log.exception("configuration reload failed; keeping the last values")
        finally:
            self._reloading = False


configuration = Configuration()
"""The process-wide configuration. Import this, not `src.config.settings`."""
