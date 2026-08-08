"""The two halves of one investigation, checked together.

An employee answers on **two channels at once**, and nothing checked that they
agreed. The reply comes back from `call` — the verdict, the accounting, the run
id. The narration goes out on `analyst.started|step|finished`, fanned out to
whoever is subscribed. A caller needs both: the portal renders the events live
and reports the reply at the end.

Every failure of one evening on the public deployment lived in that seam, and
each of them passed every test then existing:

  * an analyst returned a correct verdict while the page showed nothing, because
    its driver replays its steps only once the turn is over;
  * a reply never reached the page at all, because the task awaiting it was
    garbage-collected mid-flight — the events had arrived, the answer had not;
  * a run was declared dead after ninety seconds of silence that was simply how
    that driver works.

A test that asserts only "the call returned an answer" is blind to all three, and
so is one that asserts only "steps arrived". What follows asserts both, and that
they describe the same run.

`mock` on purpose: it exercises everything around a loop without a model, so this
costs nothing and takes a second. What is being measured is the transport.

Needs Redis. No model, no shop — hence `live` rather than `functional`.
"""

import asyncio
import uuid

import pytest
from runtime import App, Context, Params, Service

from core import Kind, topics
from core.config import load
from core.service import serve
from roles.mock.identity import IDENTITY

pytestmark = pytest.mark.live

TICKET = "Are Canadian customers able to check out?"


class Heard:
    """Everything the bus said about one investigation, in arrival order."""

    def __init__(self, reference: str) -> None:
        self.reference = reference
        self.started: list[dict] = []
        self.steps: list[dict] = []
        self.finished: list[dict] = []
        self.done = asyncio.Event()

    def take(self, bucket: list[dict], params: dict) -> None:
        # The topics carry the whole staff — another employee serving elsewhere
        # publishes onto the same three names. The reference is what makes an
        # event ours; `run_id` cannot, because it is minted by the agent and only
        # reaches us inside the first event.
        if params.get("reference") != self.reference:
            return
        bucket.append(dict(params))
        if bucket is self.finished:
            self.done.set()


@pytest.fixture
async def bus() -> tuple[Context, Heard]:
    """A served `mock`, a subscriber, and a context to call from.

    **Its own namespace.** An action has one shared consumer group, so a `mock`
    served here under the deployment's namespace would not receive every ticket
    beside the one in the agents container — the two would *split* them, silently,
    each looking like it was working normally. A namespace per run keeps this test
    from stealing a container's work, and from being confused by it.
    """
    config = load(IDENTITY.name)
    namespace = f"test-{uuid.uuid4().hex[:12]}"
    reference = f"ref-{uuid.uuid4().hex[:12]}"
    heard = Heard(reference)

    watcher = Service("bus-test", max_slots=8)
    group = f"bus-test-{uuid.uuid4().hex[:6]}"

    @watcher.event(topics.STARTED, group=group)
    async def _started(_: Context, params: Params) -> None:
        heard.take(heard.started, dict(params))

    @watcher.event(topics.STEP, group=group)
    async def _step(_: Context, params: Params) -> None:
        heard.take(heard.steps, dict(params))

    @watcher.event(topics.FINISHED, group=group)
    async def _finished(_: Context, params: Params) -> None:
        heard.take(heard.finished, dict(params))

    ready: asyncio.Future[Context] = asyncio.get_running_loop().create_future()

    @watcher.once(delay=0)
    async def _capture(ctx: Context) -> None:
        # Waited on rather than slept past: a consumer group created at `$` never
        # sees what was published before it existed, so calling before the
        # subscriptions are up loses the opening events — and looks exactly like
        # an employee that thought for a while before starting.
        if not ready.done():
            ready.set_result(ctx)

    app = App(redis=config.queue.url, namespace=namespace)
    app.include(serve(IDENTITY))
    app.include(watcher)
    # `_serve` rather than `start`: the public entry point calls `asyncio.run`,
    # which cannot run inside the loop pytest-asyncio already owns. The portal
    # does the same, for the same reason.
    task = asyncio.create_task(app._serve())  # noqa: SLF001
    try:
        ctx = await asyncio.wait_for(ready, timeout=20)
        yield ctx, heard
    finally:
        task.cancel()
        with pytest.raises((asyncio.CancelledError, Exception)):  # noqa: PT011
            await task


async def test_the_reply_and_the_narration_describe_the_same_run(
    bus: tuple[Context, Heard],
) -> None:
    """Both channels, and their agreement.

    The `run_id` cross-check is the assertion that matters. Each half can be
    right on its own while the pair is meaningless: a page showing one
    investigation's steps under another's verdict is worse than a page showing
    nothing, because it looks like it worked.
    """
    ctx, heard = bus

    reply = await ctx.call(
        IDENTITY.investigate,
        ttl="2m",
        ticket=TICKET,
        reference=heard.reference,
    )

    # ── the call ────────────────────────────────────────────────────────────
    assert reply.get("status") == "completed", f"the call failed: {reply.get('error')}"
    answer = reply.get("answer") or {}
    assert answer.get("detected"), "the reply carries no verdict"
    run_id = reply.get("run_id")
    assert run_id, "the reply names no run"

    # ── the narration ──────────────────────────────────────────────────────
    await asyncio.wait_for(heard.done.wait(), timeout=20)

    assert heard.started, "nothing was published on analyst.started"
    assert heard.steps, "the run narrated no steps"
    assert heard.finished, "nothing was published on analyst.finished"

    # ── and that they are the same run ─────────────────────────────────────
    #
    # Only the events that name a run are checked, because most do not: `step`
    # carries the reference and nothing identifying the run, by design — the
    # reference is the routing key, and `run_id` is minted by the agent and
    # reaches the caller inside the opening event. The first draft of this
    # asserted a run id on every event and failed on `{None, 'mock_…'}`, which
    # was the design answering back rather than a defect.
    named = {
        event["run_id"]
        for event in (*heard.started, *heard.steps, *heard.finished)
        if event.get("run_id")
    }
    assert named, "no event named the run at all"
    assert named == {run_id}, (
        f"the reply is run {run_id}, the events describe {named}"
    )


async def test_every_event_carries_the_reference_it_was_called_with(
    bus: tuple[Context, Heard],
) -> None:
    """The routing key, echoed untouched.

    `analyst.*` is shared by the whole staff, so a subscriber sorts its own
    events out by reference alone. An employee that dropped or rewrote it would
    still answer correctly and still narrate — into a stream nobody can attribute.
    """
    ctx, heard = bus

    await ctx.call(
        IDENTITY.investigate,
        ttl="2m",
        ticket=TICKET,
        reference=heard.reference,
    )
    await asyncio.wait_for(heard.done.wait(), timeout=20)

    every = (*heard.started, *heard.steps, *heard.finished)
    assert every, "no events at all"
    assert all(event.get("reference") == heard.reference for event in every)


async def test_the_steps_name_themselves_in_the_closed_vocabulary(
    bus: tuple[Context, Heard],
) -> None:
    """Each step says what kind it is, and the page branches on nothing else.

    This is what let the portal drop its per-lineage translation tables. A step
    arriving with a word from outside the vocabulary renders as an unknown row
    rather than failing, so nothing would report it.
    """
    ctx, heard = bus

    await ctx.call(
        IDENTITY.investigate,
        ttl="2m",
        ticket=TICKET,
        reference=heard.reference,
    )
    await asyncio.wait_for(heard.done.wait(), timeout=20)

    known = {kind.value for kind in Kind}
    spoken = {step.get("kind") for step in heard.steps}
    assert spoken, "the run narrated no steps"
    assert spoken <= known, f"steps named outside the vocabulary: {spoken - known}"
