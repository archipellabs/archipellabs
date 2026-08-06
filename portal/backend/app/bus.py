"""The portal's end of the agent bus: one call out, a stream of events back.

The company's analysts are services on a Redis-backed bus. Asking one a question
is `call("<agent>.investigate", ...)`, which blocks until the answer; while it
works the analyst publishes `started`, one `step` per thing it does, and finally
`answered` or `failed`. The two travel separately on purpose — the caller waits
for a value, a watcher receives a running commentary, and neither can slow the
other down.

This module joins those two halves back together for one HTTP request. It holds
**one** long-lived App subscribing to every agent's events, and fans each event
out in-process to whichever request asked for it.

**`reference` is the routing key.** The caller mints one per request and every
event echoes it untouched. Nothing else would do: `run_id` is assigned by the
agent and only reaches the caller inside the first event, and `started` and
`step` travel on different Redis streams, so nothing orders one before the other
— a step arriving first would be unattributable.

**One connection, not one per request.** A subscriber is a consumer with a slot
budget, and the runtime sizes its Redis pool from that budget. Opening an App per
HTTP request would open a pool per request; the ceiling is discovered as a crash
rather than a misconfiguration, which is exactly how a `MaxConnectionsError` lost
a finished investigation in this stack once already.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from runtime import App, Context, Service

log = logging.getLogger("portal.bus")

AGENTS = ("angel", "blair", "charlie", "dana", "ethan", "mock", "philip")
"""The employees that serve on the bus.

They all speak one shape now: the request arrives as `ticket`, the events go out
on the shared `analyst.*` topics with `agent` as a field, and a step names what
it is in `core.Kind`'s closed vocabulary. This list used to be three tables
describing three axes on which two lineages disagreed, and the page held a
translator for each.

`charlie` and `dana` are on it since they moved onto `core`. They used to
be absent because they carried no `Service` at all and existed only to be
launched as a subprocess by a campaign, and offering them would have advertised a
door that was not there. They now serve `charlie.investigate` and
`dana.investigate` like everyone else — which needs their processes running, as
it does for every name here.
"""

STEP_WORDS = (
    "started",
    "thinking",
    "command",
    "output",
    "message",
    "tool",
    "finished",
    "error",
)
"""What an analyst can be doing, in the closed vocabulary `core.Kind`
defines and every loop maps into.

Taken from the wire, not from the CLI watcher. An earlier version of this list
held the watcher's *display* words — `says`, `opens`, `read`, `run`, `got` — which
no agent has ever published, so every step but `thinking` arrived as `other` and
the trace rendered as one glyph repeated. Anything unmapped still lands on
`other`, which renders rather than disappears.
"""

TELEMETRY = frozenset(
    {
        "kind", "event", "reference", "agent", "run_id", "harness", "status",
        "at", "transcript", "duration_ms", "tool_calls", "model_requests",
        "input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens",
        "steps", "n",
    }
)
"""Envelope and measurement keys, stripped from what is shown as *the answer*.

The verdict and the accounting arrive in the same flat dictionary. Rendering
them together would present `cache_read_tokens` as a finding.
"""

QUEUE_DEPTH = 256
"""Events held per waiting request before the oldest are dropped.

A browser that stops reading must not be able to grow this process without
bound, and an investigation that outruns its reader is better truncated than
fatal. Generous enough that no honest run reaches it: the longest observed made
about seventy steps.
"""


class Busy(RuntimeError):
    """That analyst is already working on something.

    Every agent runs `max_slots=1`, which is a decision rather than a limit — *a
    employee is one person; two investigations at once would be two employees*. So a
    second request does not race, it queues invisibly behind the first, and a
    caller watching an empty stream cannot tell that from a failure. Refusing is
    the honest answer.

    True only while this process is the only caller. Somebody running the agent's
    own `watch` command from a terminal is invisible here, and that request will
    queue on the bus as it always did.
    """


class Requests:
    """In-flight requests, and the queues their events are delivered to.

    A plain dict rather than anything cleverer because the whole lifetime is one
    process and one event loop: a request is registered before its call is
    issued, and removed in a `finally`. The lock guards the check-then-register
    pair, which is what makes `Busy` mean anything under two simultaneous
    submissions.

    **Two resources, two lifetimes, and conflating them locked an analyst out of
    its own job.** The *agent* is busy while the investigation runs; the *queue*
    is needed until whoever asked has read the last event. One `close` did both,
    called only from the event stream's `finally` — so a request that posted and
    never opened its stream, which is a reload, a double submit or a closed tab,
    held the analyst until the process restarted. Every later attempt met "is
    already working on a question" while nothing was working. Reproduced
    deterministically: one POST with no stream, and the next POST is refused.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        self._busy: dict[str, str] = {}
        self._heard: set[str] = set()
        self._lock = asyncio.Lock()

    def heard(self, reference: str) -> bool:
        """Whether anything at all has arrived for this request.

        The proof that an analyst actually picked the ticket up. A running
        employee publishes `started` within a second or two of receiving one;
        silence means nobody is serving that name — its process is down — and
        the call will sit until its ttl expires a quarter of an hour later.
        """
        return reference in self._heard

    async def open(self, agent: str) -> tuple[str, asyncio.Queue[dict[str, Any] | None]]:
        async with self._lock:
            if agent in self._busy:
                raise Busy(f"{agent} is already working on a question")
            reference = uuid.uuid4().hex
            self._busy[agent] = reference
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(QUEUE_DEPTH)
            self._queues[reference] = queue
            return reference, queue

    async def done(self, agent: str, reference: str) -> None:
        """The analyst has finished. Free it, whoever is or is not listening.

        Called from the work task rather than from the stream, because the work
        task is the only thing that knows when the investigation ended. The
        queue outlives this: a reader may still have the terminal event to
        collect, and dropping it here would lose the answer to a browser that
        connected a moment late.
        """
        async with self._lock:
            if self._busy.get(agent) == reference:
                del self._busy[agent]

    async def close(self, agent: str, reference: str) -> None:
        """The reader has gone. Drop its queue, and free the analyst if the work
        somehow ended without saying so."""
        async with self._lock:
            self._queues.pop(reference, None)
            self._heard.discard(reference)
            if self._busy.get(agent) == reference:
                del self._busy[agent]

    def queue_for(self, reference: str) -> "asyncio.Queue[dict[str, Any] | None] | None":
        return self._queues.get(reference)

    def agent_for(self, reference: str) -> str | None:
        return next((a for a, r in self._busy.items() if r == reference), None)

    def deliver(self, event: dict[str, Any]) -> None:
        """Hand one event to the request that asked for it, if it is still there.

        Silently dropped when the reference is unknown — the request has already
        finished or was never ours. An agent publishes to everyone, so receiving
        events for somebody else's call is the normal case, not an error.
        """
        reference = str(event.get("reference") or "")
        queue = self._queues.get(reference)
        if queue is None:
            return
        # Noted before the queue is touched: this is what tells the work task
        # that somebody is actually serving this name.
        self._heard.add(reference)
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("dropping an event: reader is not keeping up")


requests = Requests()
watcher = Service("portal", max_slots=len(AGENTS) * 2)
"""One subscriber for the whole staff.

The budget is two slots per agent rather than one: `answered` and a trailing
`step` can be in flight together, and a subscriber that serialises them adds
latency to the only thing the reader is waiting for.
"""


def as_step(params: dict[str, Any]) -> dict[str, Any]:
    """One step, in the page's vocabulary.

    **No branch on who is speaking, and that is the whole point of the
    migration.** Every employee names the step itself in `kind`, from
    `core.Kind`'s closed vocabulary. This function used to hold a table
    per lineage, keyed off the agent's name, because two of them narrated in an
    `event` field with words of their own and carried the payload under `args`
    or `result` depending on which side of a call it was.

    The one thing still worth doing is renaming `kind`, which is also the
    portal's own envelope key: merging the payload untouched overwrites the
    analyst's word with the string `"step"` and collapses every glyph to one.
    """
    word = str(params.get("kind") or "")
    return {
        "step": word if word in STEP_WORDS else "other",
        "text": str(params.get("text") or params.get("command") or ""),
        "tool": str(params.get("tool") or params.get("skill") or ""),
    }


def _subscribe(topic: str, kind: str) -> None:
    """Register one event handler, named so the runtime can tell them apart."""

    async def handler(_: Context, params: dict[str, Any]) -> None:
        event = {k: v for k, v in params.items() if k != "kind"}
        event["kind"] = kind
        if kind == "step":
            event.update(as_step(params))
        requests.deliver(event)

    handler.__name__ = "on_" + topic.replace(".", "_")
    watcher.event(topic, group="portal")(handler)


# The shared topics are subscribed **once**, not once per agent: they are three
# Redis streams carrying the whole staff, and registering the same name twice
# would be two consumers competing for one stream — each employee's events
# would reach one of them, arbitrarily. Routing by `reference` is what makes one
# subscription sufficient: an event for a call this process did not make finds
# no queue and is dropped, which is the normal case rather than an error.
for _kind in ("started", "step"):
    _subscribe(f"analyst.{_kind}", _kind)

# **The closing events are deliberately not subscribed.** Neither lineage's
# terminal event is a usable answer: Philip's `answered` carries only a
# confidence and a step count — the verdict itself is the *return value* of the
# call — and the shared lineage's `finished` carries the verdict flat, mixed in
# with its token accounting. Ending the stream on either one would have meant
# reading the answer from whichever half of the bus happened to have it, and for
# Philip that half is empty, which is precisely how this page first rendered
# "the analyst answered with an empty result" for a run that had answered fine.
#
# So the verdict comes from `call`, which is what `call` is for, and `main.ask`
# puts the single terminal event on the queue itself. The cost is a genuine one:
# events and replies travel on different streams, so a last step still in flight
# when the reply lands is cut. A trailing step lost is a smaller failure than an
# answer never shown.


_ready: asyncio.Future[Context] | None = None


@watcher.once(delay=0)
async def _capture(ctx: Context) -> None:
    """Keep the context the App built, so HTTP requests can issue calls.

    **This is a workaround for a gap in the runtime, and it should not survive
    contact with a fix.** `call()` needs a rendezvous — a node that owns the
    reply list and the pending-future map — and the only way to get one is to be
    handed a `Context` by the App, which happens inside a handler or a producer.
    A web process has neither: its work arrives on an HTTP connection at a moment
    the bus knows nothing about.

    So a producer that runs once at boot hands its context out and returns. The
    context stays valid because the node and the broker belong to the App, not to
    this coroutine.

    What would remove it is an accessor on `App` for the context it already
    builds. Until then this is the seam, named rather than hidden.
    """
    if _ready is not None and not _ready.done():
        _ready.set_result(ctx)


class Bus:
    """The App, held for the process's lifetime, plus the one verb the portal uses."""

    def __init__(self, redis_url: str, namespace: str) -> None:
        self._app = App(redis=redis_url, namespace=namespace)
        self._app.include(watcher)
        # Kept because the sweep needs its own connection: the runtime offers no
        # accessor for the one it holds, and reaching in for a private client
        # would couple this to its internals.
        self._redis = redis_url
        self._namespace = namespace
        self._task: asyncio.Task[None] | None = None
        self._ctx: Context | None = None

    async def start(self) -> None:
        global _ready
        _ready = asyncio.get_running_loop().create_future()
        # `_serve` rather than `start`: the public entry point calls
        # `asyncio.run`, which cannot be used from inside the loop uvicorn is
        # already running. The second half of the same gap as `_capture` above.
        self._task = asyncio.create_task(self._app._serve())  # noqa: SLF001
        # Waiting on the producer rather than sleeping a fixed time: it fires
        # once the subscriptions exist, and a group created at `$` never sees a
        # message published before it — a request submitted too early would
        # stream nothing and look broken.
        self._ctx = await asyncio.wait_for(_ready, timeout=30)
        await self._sweep()

    async def _sweep(self) -> None:
        """Forget the consumers earlier instances of this portal left behind.

        **This process is where they come from.** Its watcher is sized at two
        slots per employee, so every start registers fourteen consumers on each
        shared topic, and every restart abandons fourteen more. One afternoon of
        restarts left 160 of them — against three per agent, which have a single
        slot each.

        They cost nothing to run against: a dead consumer never pulls, so no
        event is delivered into a void. What they cost is the ability to read
        `XINFO GROUPS` as a measure of anything.

        Two rules keep it safe. **Never a consumer holding pending entries** —
        `DELCONSUMER` acknowledges them to nobody, and the simulator shares this
        Redis and does hold unacked messages. And **only this process's own
        groups**: deciding a neighbour is dead is not a housekeeping task. A
        live-but-idle consumer swept early simply re-registers, having lost
        nothing, because it held nothing.

        The right home is the runtime, on shutdown. `core.sweep` carries
        the same twenty lines for the employees, and the duplication is
        deliberate: this image ships without the agents' package.
        """
        idle_ms = 30 * 60 * 1000
        client = None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self._redis, decode_responses=True)
            swept = 0
            for kind in ("started", "step", "finished"):
                stream = f"{self._namespace}:evt:analyst.{kind}"
                try:
                    consumers = await client.xinfo_consumers(stream, "portal")
                except Exception:  # noqa: BLE001 — nobody has written to it yet
                    continue
                for consumer in consumers:
                    if int(consumer.get("pending") or 0) > 0:
                        continue
                    # `idle` and not `inactive`. Redis answers `-1` for the
                    # latter where it has nothing to say, and `-1` is truthy —
                    # so `inactive or idle` picks the sentinel, every consumer
                    # measures as "silent for -1 ms", and the sweep completes
                    # having deleted nothing. It reported success by saying
                    # nothing, which is the failure this stack keeps finding in
                    # its own instruments.
                    ages = [
                        int(consumer.get(field) or 0)
                        for field in ("idle", "inactive")
                        if isinstance(consumer.get(field), int | float)
                    ]
                    if max([age for age in ages if age >= 0], default=0) < idle_ms:
                        continue
                    with contextlib.suppress(Exception):
                        await client.xgroup_delconsumer(
                            stream, "portal", consumer["name"]
                        )
                        swept += 1
            if swept:
                log.info("swept %d consumer(s) left by earlier portals", swept)
        except Exception:  # noqa: BLE001 — housekeeping never blocks a start
            log.debug("could not sweep the portal's own consumers", exc_info=True)
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.aclose()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def ask(
        self, agent: str, question: str, model: str, effort: str, reference: str
    ) -> dict[str, Any]:
        """Put the question, and wait for the answer the analyst returns.

        One field name for everyone. It was two — this page carried a table
        mapping each employee to what it called the thing being asked, because
        two lineages had been built with different words for it. Sending the
        wrong one is not a soft failure: the request is validated against the
        agent's own model, so it comes back as a rejection before any work
        starts, visible only to whoever reads the error.
        """
        if self._ctx is None:
            raise RuntimeError("the bus is not connected yet")
        return await self._ctx.call(
            f"{agent}.investigate",
            ticket=question,
            reference=reference,
            model=model,
            effort=effort,
            ttl="15m",
        )

    async def describe_config(self) -> dict[str, Any]:
        """Everything the simulator will let anyone change, and its current value.

        Asked of the simulator rather than read from its database, though the
        portal holds a connection to that database and could. Two reasons, and
        the second is the real one: the layering — a value may come from an
        override, the environment, or the shipped default — lives in the
        simulator's configuration service, so a reader going straight to the
        table would see only the top layer and would have to reimplement the
        other two to say where a value came from. And the set of keys that may
        be changed is the simulator's own judgement, stated in `TUNABLES`;
        asking keeps that judgement in one place instead of copying it here to
        drift.
        """
        if self._ctx is None:
            raise RuntimeError("the bus is not connected yet")
        return await self._ctx.call("config.describe", ttl="30s")

    async def apply_config(self, key: str, value: Any) -> dict[str, Any]:
        """Change one knob, and report the layer that now answers.

        `value=None` is the simulator's sentinel for **reset** — drop the
        override and fall back to the environment or the shipped default. It is
        passed through rather than translated, because inventing a second
        vocabulary for the same idea is how the two ends stop agreeing.

        An unknown key raises on the simulator's side and arrives here as a
        failed call. That is deliberate over there: a control plane that accepts
        a key one letter off and reports success is worse than one with no typo
        protection at all.
        """
        if self._ctx is None:
            raise RuntimeError("the bus is not connected yet")
        return await self._ctx.call("config.apply", key=key, value=value, ttl="30s")


def settled(result: dict[str, Any]) -> dict[str, Any]:
    """The reply to a call, as the one terminal event the page reads.

    One envelope for everyone: telemetry flat, verdict nested under `answer`.
    There were three shapes — one lineage wrapped its verdict, another returned
    it flat among its token counts, a third did something else again — and the
    `TELEMETRY` strip below is what is left of reconciling them. It still earns
    its place: a page that showed the verdict and the accounting together
    presented `cache_read_tokens` as a finding.

    A crash is reported **as a value rather than an exception**, on the stated
    grounds that "the analyst crashed after twenty tool calls" is a result worth
    keeping, not an error that loses the transcript with it. So the status field
    is the only thing separating an answer from a failure here, and a shape that
    announces neither is treated as an answer: an analyst that returned
    something has not failed.
    """
    status = str(result.get("status") or "")
    if status in ("failed", "crashed", "error"):
        reason = result.get("detail") or result.get("error") or f"the run {status}"
        return {"kind": "failed", "reason": str(reason), "spent": spent(result)}

    verdict = result.get("answer")
    return {
        "kind": "answered",
        "answer": (
            {k: v for k, v in verdict.items() if k not in TELEMETRY}
            if isinstance(verdict, dict)
            else {}
        ),
        "spent": spent(result),
    }


SPENT = (
    "run_id", "harness", "model", "effort", "duration_ms", "tool_calls",
    "model_requests", "input_tokens", "output_tokens", "reasoning_tokens",
    "cache_read_tokens", "cost", "estimated_cost",
)
"""What a run consumed, as the envelope reports it.

Beside the verdict rather than inside it, which is the whole reason `TELEMETRY`
exists: a page that rendered these among the answer's fields presented
`cache_read_tokens` as a finding. Kept apart, they can finally be *shown* — until
now `settled` dropped every one of them, so the accounting travelled the length
of the bus and died at the last step, and the page could not display what it
never received.
"""


def spent(result: dict[str, Any]) -> dict[str, Any]:
    """The run's accounting, with the measured and the reckoned kept apart.

    **Nothing here is computed — every number is passed through.** The employee
    prices its own run at its final return, because it is the thing that knows
    which model it ran; a price table kept here would be a second one, and two
    tables agree only until they do not. `cost` is what a loop was billed and
    `estimated_cost` is tokens at a transcribed rate, and they arrive under
    separate names because they are separate claims.

    A model nobody has priced yields neither, which is the honest answer and the
    common one. Unpriced is not free.
    """
    return {key: result[key] for key in SPENT if result.get(key) is not None}


async def stream(
    queue: asyncio.Queue[dict[str, Any] | None],
) -> AsyncIterator[dict[str, Any]]:
    """Events for one request, until the analyst finishes or fails.

    Terminates on the terminal event rather than on the call returning: the
    answer arrives on both paths, and ending here means the reader sees the last
    step before the stream closes rather than after it.
    """
    while True:
        event = await queue.get()
        if event is None:
            return
        yield event
        if event.get("kind") in ("answered", "failed"):
            return
