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

**Two kinds of key, two backing stores.** That split is the whole design here:

* A **value** — `base_arrivals_per_minute`, `market_mix`, `fast`. Lives in the
  settings table. Applying it is a write; nothing else has to happen, because
  every consumer re-reads it (the tick each pass, the journey each customer).
* A **flow** — `customer-journey`, `catalog-doctor`. Lives in the runtime's
  switch registry. Applying it flips a switch, which pauses *consumption* while
  the stream keeps filling, so resuming drains the backlog rather than losing it.

A flow is not stored as a setting, deliberately. The switch registry is already
durable (a Redis hash) and already authoritative — every worker checks it on its
own timer. Mirroring it into the settings table would create a second source of
truth for "is this running", and the two would disagree the first time anyone
used `runtime.switches` directly.

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

service = Service("configuration", max_slots=1)


async def _apply_flow(ctx: Context, name: str, value: Any) -> dict[str, Any]:
    """Pause or resume a mounted flow. `None` resets, which means running."""
    running = True if value is None else value
    if not isinstance(running, bool):
        raise ValueError(f"{name!r} is a flow switch and takes true or false")

    await ctx.set_enabled(name, running)
    log.info("flow %s %s", name, "resumed" if running else "paused")
    return {"key": name, "kind": "flow", "running": running}


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

    What a settings UI renders. Flows report `running` from the switch snapshot
    this process holds, so a flip made elsewhere shows up within the switchboard's
    refresh interval rather than instantly.
    """
    return {
        "values": await configuration.describe(),
        "flows": {
            name: {"running": ctx.is_enabled(name), "what": what}
            for name, what in sorted(FLOW_SWITCHES.items())
        },
    }
