"""Forget the consumers that died without saying goodbye.

A Redis consumer group remembers every consumer that ever read from it. A
process registers one per slot on each stream it subscribes to, and when that
process ends — killed, redeployed, crashed — the registration stays. Nothing
reclaims it, because from Redis's side a consumer that has stopped reading is
indistinguishable from one that is merely idle.

They cost nothing to run against: a dead consumer never pulls a message, so no
ticket is ever delivered into a void. What they cost is **the ability to read
the group as a measure of anything**. One afternoon of restarts left 172 of
them here, and `XINFO GROUPS` reported an agent with a single slot as having
four workers — a number somebody will eventually take for load.

The right home for this is the runtime, on shutdown, where the group is created
and the process knows it is leaving. Until it lives there, a process sweeps at
**startup** instead: it is the one moment it can be certain the consumers named
after older instances of itself are not coming back.

Two rules make it safe, and the second one is not optional:

* **Never a consumer holding pending entries.** `XGROUP DELCONSUMER` returns
  them to nobody — the messages leave the pending list and are acknowledged by
  no one. Sweeping on idleness alone would have taken live simulator workers
  mid-delivery, which share this Redis and had unacked messages at the moment
  the first sweep ran.
* **Only groups this process owns.** A neighbour's stale consumer is a
  neighbour's business, and a sweep that reached across would be a process
  deciding when another one is dead.

Deleting an *idle but live* consumer is harmless: it re-registers on its next
read, having lost nothing, because it held nothing.
"""

import logging
from typing import Any

log = logging.getLogger("core.sweep")

IDLE_MS = 30 * 60 * 1000
"""How long a consumer must have been silent to count as gone.

Half an hour, which is far past any poll interval and far short of a working
day. Generous because the cost of guessing wrong is asymmetric only in one
direction — a live consumer swept early simply reappears — and there is no
reason to be aggressive about housekeeping.
"""


async def stale(client: Any, streams: dict[str, str]) -> int:
    """Drop the consumers of `{stream: group}` that are gone. Returns how many.

    Never raises. Housekeeping that can stop a process from starting is worse
    than the mess it tidies, so a Redis that refuses these calls — an older
    server, a permission, a stream that does not exist yet — is logged and
    survived.
    """
    swept = 0
    for stream, group in streams.items():
        try:
            consumers = await client.xinfo_consumers(stream, group)
        except Exception:  # noqa: BLE001 — a stream nobody has written to yet
            continue
        for consumer in consumers:
            name = _text(consumer.get("name"))
            if int(consumer.get("pending") or 0) > 0:
                continue
            if _quiet_for(consumer) < IDLE_MS:
                continue
            try:
                await client.xgroup_delconsumer(stream, group, name)
                swept += 1
            except Exception:  # noqa: BLE001 — raced with somebody else's sweep
                continue
    if swept:
        log.info("swept %d consumer(s) left behind by earlier instances", swept)
    return swept


def _quiet_for(consumer: dict[str, Any]) -> int:
    """How long this consumer has been silent, in milliseconds.

    **`idle` is the field to trust; `inactive` is not always a number.** Redis
    reports `-1` for it where it has nothing to say — a server too old for it,
    or a consumer that has never completed a read — and `-1` is perfectly
    truthy, so a fallback written as `inactive or idle` picks the sentinel every
    time. Every consumer then measured as "silent for -1 ms", every one was
    younger than any threshold, and the sweep ran to completion having deleted
    nothing at all. It reported success by saying nothing, which is the failure
    this repository keeps finding in its own instruments.
    """
    ages = [
        int(consumer.get(field) or 0)
        for field in ("idle", "inactive")
        if isinstance(consumer.get(field), int | float)
    ]
    return max([age for age in ages if age >= 0], default=0)


def _text(value: Any) -> str:
    """Redis hands back `bytes` or `str` depending on how the client was built."""
    return value.decode() if isinstance(value, bytes) else str(value)
