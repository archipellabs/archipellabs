"""Mounting an employee on the bus — the one place any of them does it.

Six agents used to carry a copy of this file. They were the same copy: a
`Service`, one action, a closure translating events onto topics, and a call to
the loop. The copies drifted anyway — two of them took the request under a
different field name and published on different topics — and a page trying to
call all six through one door found there was no door.

The action carries the employee's name; the events do not. That asymmetry is the
whole of `topics`, and it is load-bearing: an action has exactly one correct
executant, so two containers serving `analyst.investigate` would split the
tickets between themselves silently, each looking like it was working normally.
Events fan out instead — one consumer group per subscriber — so a portal tailing
`analyst.step` sees the whole staff and keeps seeing it when the next one is
hired.
"""

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from runtime import App, Context, Service

from core import run, sweep, topics
from core.config import Config, load
from core.contract import Ticket
from core.harness.base import Identity

log = logging.getLogger("core.service")


@dataclass(frozen=True)
class BusNarrator:
    """Publishes an investigation's events, stamped so they can be routed back.

    Every event carries `agent` and `reference`, and they are merged rather than
    passed as keywords beside the fields: the finished envelope is splatted
    through the same call, and a duplicate keyword is a `TypeError` raised at
    binding time — the shape of bug that once killed a run at its very last step,
    after ten minutes of work. The caller's own id wins over anything an
    investigation happened to produce under that name.

    **`reference` rides on every event, steps included.** It is the only key a
    subscriber has for routing one back to whoever asked. Learning the run id
    from `started` first does not work: the three topics are three Redis streams
    and nothing orders one before another, so a step that overtakes the start is
    a step attributable to nobody — and the opening steps are exactly the ones a
    page fanning these out to a live connection would drop, looking for all the
    world like a network fault.
    """

    ctx: Context
    agent: str
    reference: str | None

    async def started(self, **fields: Any) -> None:
        await self._emit(topics.STARTED, fields)

    async def step(self, **fields: Any) -> None:
        await self._emit(topics.STEP, fields)

    async def finished(self, **fields: Any) -> None:
        await self._emit(topics.FINISHED, fields)

    async def _emit(self, topic: str, fields: dict[str, Any]) -> None:
        # `emit`, not `dispatch`: nobody is waiting on these, any number of
        # subscribers may want them, and a step that reaches no one is not an
        # error.
        await self.ctx.emit(
            topic, **{**fields, "agent": self.agent, "reference": self.reference}
        )


def serve(
    identity: Identity,
    *,
    slots: int = 1,
    config: Callable[[], Config] | None = None,
) -> Service:
    """The employee, as a service the bus can route to.

    `slots=1` is not arbitrary. A role is one person: two investigations at once
    would be two employees. When that stops being true it should be a decision,
    not a default.

    `config` is injectable so a test can mount an employee without an
    environment. It is called per ticket rather than once, which is what makes
    the environment a default the caller can override: `for_call` hands back a
    copy, because this process outlives every ticket and a choice written onto
    the shared object would answer somebody else's question at a depth they never
    asked for.
    """
    service = Service(identity.name, max_slots=slots)
    # **Named.** `load` on its own reads only the shared variables, so an
    # employee served here would ignore its own `PHILIP_HARNESS`,
    # `<AGENT>_MODEL`, `<AGENT>_EFFORT` and `<AGENT>_TIMEOUT_S` — philip would
    # answer every ticket on codex however its `.env` was written, and nothing
    # would say so. The same defect was found and fixed in the campaign's worker
    # the same day it was written here; a default argument is easy to forget
    # twice.
    read_config = config or (lambda: load(identity.name))

    @service.action(identity.investigate, params=Ticket)
    async def investigate(ctx: Context, params: Ticket) -> dict[str, Any]:
        """Take a question, run the loop, publish and return the outcome.

        Returns rather than raises, whatever happens — `run.investigate` holds
        that contract. The caller asked a question and deserves a value it can
        read; an exception would say the bus failed, which is a different fact
        and usually not the true one.
        """
        return await run.investigate(
            identity,
            read_config().for_call(params.model, params.effort),
            params.ticket,
            reference=params.reference,
            narrator=BusNarrator(ctx, identity.name, params.reference),
        )

    @service.once(delay=0)
    async def sweep_own(_: Context) -> None:
        """Forget the consumers earlier instances of this employee left behind.

        A one-shot producer rather than a call in `app_for`, because that runs
        **before** `App.start()` creates the loop — `ensure_future` there raises
        `no current event loop` and takes the whole process down with it. Every
        agent failed to boot, and the unit tests could not see it: they exercise
        the handler, never the App. Housekeeping that stops a process from
        starting is worse than the mess it tidies, which is why everything below
        is also caught.
        """
        queue = read_config().queue
        stream = f"{queue.namespace}:act:{identity.investigate}"
        client = None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(queue.url, decode_responses=True)
            await sweep.stale(client, {stream: "workers"})
        except Exception:  # noqa: BLE001 — never blocks a start
            log.debug("could not sweep %s", stream, exc_info=True)
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.aclose()

    log.debug("%s serves %s", identity.name, identity.investigate)
    return service


def app_for(*identities: Identity, level: str = "") -> App:
    """These employees as one process the bus can reach.

    Seven agents each held a byte-identical copy of this — the same four lines,
    differing only in the docstring above them.

    **Several, because a deployment should decide how many processes this is.**
    One container per employee isolates them: philip exhausting itself leaves
    angel answering. One container for all seven is a quarter of the memory and
    one thing to restart. Neither is right everywhere, and nothing about an
    employee changes between them — each `Service` keeps its own `max_slots=1`
    and its own named configuration, and the bus still routes on
    `<agent>.investigate`, so a caller cannot tell which arrangement it reached.

    The queue is read from the *first* identity's configuration. All seven share
    one `.env`, so this is one value read seven ways; taking it from one of them
    rather than merging seven keeps the failure obvious if that ever stops being
    true — a mismatch would be two employees on two namespaces, which looks like
    an agent that never answers.

    Returns the `App` rather than starting it, so a caller that grows another
    service can still `include` one. Starting is the caller's line.

    `level` configures logging, which a library has no business doing on import
    but a process entry point must do somewhere: passed explicitly, it is the
    process's decision rather than a side effect of importing this module.
    """
    if not identities:
        raise ValueError("app_for needs at least one identity to mount")
    if level:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    cfg = load(identities[0].name)
    app = App(redis=cfg.queue.url, namespace=cfg.queue.namespace)
    for identity in identities:
        app.include(serve(identity))
    return app

