"""The configuration control plane — changing a knob on a running simulator.

    summary = await ctx.call(Topic.CONFIG_APPLY, key="base_arrivals_per_minute", value=9)

A queue action rather than an HTTP endpoint, because the simulator has no web
server and should not grow one to be steerable: the runtime already gives us a
named, authenticated, at-least-once channel, and this rides it like any other
work. `call` rather than `dispatch`, so a caller learns whether its change was
accepted — a settings UI that cannot report "rejected: input should be a valid
number" is a settings UI that lies.

**The write path lives here; the read path is a service.** `services/configuration`
is a library every flow imports to *read* a setting, on the hot path, with no
`await`. This is the other half: a mounted flow, imported by nobody, that exists
to *change* one. Splitting them along that line keeps the thing every tick calls
free of the queue, the database writes and the switch registry.

**Two kinds of key, one store.** Both live in `simulator_setting`, because both
are configuration and configuration is durable:

* A **value** — `base_arrivals_per_minute`, `market_mix`, `fast`. Applying it is
  a write and nothing else has to happen, because every consumer re-reads it (the
  tick each pass, the journey each customer).
* A **flow flag** — `customer-journey`, `catalog-doctor`. Applying it is a write
  *and* a projection: the database records the decision, then the runtime's
  switch registry is updated so workers stop claiming. Pausing stops consumption
  while the stream keeps filling, so resuming drains the backlog.

The registry is not a second source of truth, it is a **cache with a job**. Only
the runtime can enforce a pause — the check lives inside the claim loop, and
nothing outside it can stop a worker taking new work. But that registry is a
Redis hash, and Redis here is transport: no named volume, AOF off, wiped with the
stack. State that must survive cannot live there. So the database decides and
Redis carries the decision, which is why `replay_flow_flags` re-projects at boot
and why `describe` reports `running` from the database rather than reading the
copy back.

**What this cannot do.** A switch pauses something *mounted*. A service left out
by `include(enabled=False)` was never constructed and its lifespan never ran, so
no switch reaches it — which is why the `*_enabled` settings stay static wiring
and are not offered here. Asking for a flow this process did not mount is an
error, not a silent success.
"""

import logging
from typing import Any

from runtime import Context, Params, Service

from src.services.configuration.service import TUNABLES, configuration
from src.technical_flows.contracts import ConfigChange
from src.technical_flows.topics import Topic

log = logging.getLogger("simulator.configuration")

FLOW_SWITCHES: dict[str, str] = {
    "customer-journey": "the browser pool that drives simulated customers",
    "customer-arrivals": "the producer that dispatches new arrivals",
    "catalog": "catalog sync with the storefront",
    "catalog-doctor": "the periodic drift check that calls catalog sync",
    "stock-refill": "the periodic top-up of tracked products",
    "payment-settlement": "the periodic acceptance of waiting bank wires",
}
"""Flows that can be paused, keyed by their runtime switch name.

The keys are the runtime's own names — the ones `App` prints in its topology and
`runtime.switches` takes — not a parallel vocabulary invented here. One name for
one thing is worth more than keys that read prettily in a UI.

Service names, not registration names, except for `catalog-doctor`. A service
name is a master switch over everything it registers, and it is unambiguous:
three services each register a producer with `id='tick'`, so a switch on `tick`
would pause all three at once.
"""

FLOW_ENABLE_FLAGS: dict[str, tuple[str, ...]] = {
    "customer-journey": ("journey_enabled",),
    "customer-arrivals": ("arrivals_enabled",),
    "catalog": ("catalog_enabled",),
    "catalog-doctor": ("catalog_enabled", "catalog_doctor_enabled"),
    "stock-refill": ("stock_enabled",),
    "payment-settlement": ("payments_enabled",),
}
"""Static wiring that must be present before a runtime switch can do anything."""

service = Service("configuration", max_slots=1)


def _flow_is_mounted(name: str) -> bool:
    return all(configuration.get(flag) for flag in FLOW_ENABLE_FLAGS[name])


async def _apply_flow(ctx: Context, name: str, value: Any) -> dict[str, Any]:
    """Pause or resume a mounted flow. `None` resets, which means running.

    Database first, registry second, and the order is the point. The database is
    where the decision lives; the switch registry is how it reaches the workers
    that enforce it. If the projection fails, the flag is still recorded and the
    next boot replays it — the reverse would leave a pause that no longer exists
    anywhere after a stack wipe.
    """
    if not _flow_is_mounted(name):
        flags = ", ".join(flag.upper() for flag in FLOW_ENABLE_FLAGS[name])
        raise ValueError(
            f"{name!r} is not mounted; enable {flags} and restart before switching it"
        )
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{name!r} is a flow switch and takes true or false")

    running = await configuration.set_running(name, value)
    await ctx.set_enabled(name, running)
    log.info("flow %s %s", name, "resumed" if running else "paused")
    return {"key": name, "kind": "flow", "mounted": True, "running": running}


@service.once(id="flow-flags")
async def replay_flow_flags(ctx: Context) -> None:
    """Project the stored flags onto the switch registry at boot.

    Redis is the runtime's transport and is wiped with the stack, so the registry
    starts empty — meaning "everything running" — while the database still holds
    the flags someone set. Without this, every restart silently resumes every
    paused flow.

    It writes all of them, not just the paused ones, so the registry *converges*
    on the database. That also means a flip made straight into Redis with
    `runtime.switches` is undone at the next boot: it never went through the
    place the decision is kept.
    """
    await configuration.refresh()
    for name in FLOW_SWITCHES:
        await ctx.set_enabled(name, configuration.is_running(name))
    paused = sorted(
        name for name in FLOW_SWITCHES if not configuration.is_running(name)
    )
    log.info("flow flags restored from the database; paused: %s", paused or "none")


async def _apply_value(key: str, value: Any) -> dict[str, Any]:
    """Store or drop an override, and report the layer that now answers."""
    if value is None:
        await configuration.clear(key)
    else:
        await configuration.set(key, value)
    return {"key": key, "kind": "value", **(await configuration.describe())[key]}


@service.action(Topic.CONFIG_APPLY, params=ConfigChange)
async def apply(ctx: Context, change: ConfigChange) -> dict[str, Any]:
    """Change one knob, and report what it now reads.

    Raises rather than shrugging when the key is unknown: a control plane that
    accepts `{"key": "base_arrival_per_minute"}` — one letter off — and returns
    success is worse than one that has no typo protection at all, because the
    caller stops looking.
    """
    if change.key in FLOW_SWITCHES:
        return await _apply_flow(ctx, change.key, change.value)
    if change.key in TUNABLES:
        return await _apply_value(change.key, change.value)
    raise KeyError(
        f"{change.key!r} cannot be changed at runtime. "
        f"Values: {sorted(TUNABLES)}. Flows: {sorted(FLOW_SWITCHES)}."
    )


@service.action(Topic.CONFIG_DESCRIBE)
async def describe(ctx: Context, params: Params) -> dict[str, Any]:
    """Everything changeable, its current value, and where that value came from.

    What a settings UI renders. `mounted` is the static wiring decision; `running`
    is meaningful only when mounted and comes from the switch snapshot this
    process holds. A flip made elsewhere shows up within the switchboard's refresh
    interval rather than instantly.
    """
    flows: dict[str, dict[str, Any]] = {}
    for name, what in sorted(FLOW_SWITCHES.items()):
        mounted = _flow_is_mounted(name)
        flows[name] = {
            "mounted": mounted,
            # From the database, not from `ctx.is_enabled`: the registry is a
            # projection, and reading it back would report the copy rather than
            # the decision — including during the window where the two disagree.
            "running": mounted and configuration.is_running(name),
            "what": what,
        }
    return {"values": await configuration.describe(), "flows": flows}
