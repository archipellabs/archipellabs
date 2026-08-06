"""The bus mount — the copy six agents used to each carry, and which drifted."""

import pytest

from core import mock
from core.config import load
from core.contract import Ticket
from core.harness.base import Identity
from core.service import BusNarrator, serve
from core.topics import FINISHED, STARTED, STEP


class RecordingContext:
    """A `Context` that keeps what was published instead of publishing it."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    async def emit(self, topic: str, **params) -> None:
        self.emitted.append((topic, params))

    def on(self, topic: str) -> list[dict]:
        return [params for name, params in self.emitted if name == topic]


@pytest.fixture(autouse=True)
def runs_here(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "runs"))


@pytest.fixture
def identity() -> Identity:
    return Identity("mock", mock.build(steps=3))


async def test_every_event_says_who_is_speaking_and_who_asked(identity):
    """`agent` is a field rather than a topic, which is what lets one
    subscription follow the whole staff. `reference` is the only key a subscriber
    has for routing an event back to whoever asked."""
    ctx = RecordingContext()
    narrator = BusNarrator(ctx, "mock", "req-42")

    await narrator.started(run_id="mock_1")
    await narrator.step(n=1, kind="thinking")
    await narrator.finished(run_id="mock_1", status="completed")

    assert [topic for topic, _ in ctx.emitted] == [STARTED, STEP, FINISHED]
    assert all(params["agent"] == "mock" for _, params in ctx.emitted)
    assert all(params["reference"] == "req-42" for _, params in ctx.emitted)


async def test_the_caller_s_id_wins_over_one_the_run_produced():
    """The finished envelope is splatted through this same call, and it carries
    a `reference` of its own. A duplicate keyword is a TypeError raised at
    binding time — the shape of bug that killed a run at its very last step."""
    ctx = RecordingContext()

    await BusNarrator(ctx, "mock", "req-42").finished(
        run_id="mock_1", reference="whatever-the-run-said", agent="not-this"
    )

    published = ctx.on(FINISHED)[0]
    assert published["reference"] == "req-42"
    assert published["agent"] == "mock"


def test_an_employee_answers_to_its_own_name(identity):
    """An action has exactly one correct executant: two containers serving one
    action name would split the tickets between themselves, silently, and each
    would look like it was working normally. The name is the only defence."""
    service = serve(identity)

    assert service.name == "mock"
    assert [c.name for c in service.consumers] == ["mock.investigate"]
    assert service.max_slots == 1, "a role is one person"


async def test_a_mounted_employee_narrates_and_answers(identity, monkeypatch):
    """The whole path, without a broker: a ticket in, events out, envelope back."""
    monkeypatch.setenv("AGENT_MODEL_NAME", "a-model")
    service = serve(identity, config=load)
    handler = _action_of(service)
    ctx = RecordingContext()

    envelope = await handler(ctx, Ticket(ticket="sales look off", reference="req-7"))

    assert envelope["status"] == "completed"
    assert envelope["reference"] == "req-7"
    assert len(ctx.on(STARTED)) == 1
    assert len(ctx.on(FINISHED)) == 1
    assert ctx.on(STEP)


async def test_a_ticket_chooses_the_model_and_the_depth(identity, monkeypatch):
    """The environment is the default and the ticket overrides it, which is what
    lets a portal offer both per question rather than per deployment."""
    monkeypatch.setenv("AGENT_MODEL_NAME", "the-deployment-s-model")
    monkeypatch.setenv("AGENT_MODEL_REASONING", "medium")
    handler = _action_of(serve(identity, config=load))

    envelope = await handler(
        RecordingContext(),
        Ticket(ticket="sales look off", model="a-chosen-model", effort="high"),
    )

    assert envelope["model"] == "a-chosen-model"
    assert envelope["effort"] == "high"


def _action_of(service):
    """The one handler `serve` registered, called as the runtime would call it."""
    (registered,) = service.consumers
    return registered.handler


async def test_a_served_employee_reads_its_own_environment(identity, monkeypatch):
    """The default that was easy to forget twice.

    `serve` used to hand `load` itself to the handler, so it was called with no
    agent name and read only the shared variables. An employee mounted here
    ignored its own `<AGENT>_MODEL`, `<AGENT>_EFFORT`, `<AGENT>_HARNESS` and
    `<AGENT>_TIMEOUT_S` — philip would have answered every ticket on codex
    however its `.env` was written, and nothing would have said so.

    Asserted through the real environment rather than an injected loader: a test
    that passes `config=load` proves only that the injection works, which is
    exactly how this survived its first test.
    """
    monkeypatch.setenv("AGENT_MODEL_NAME", "the-shared-model")
    monkeypatch.setenv("AGENT_MODEL_REASONING", "medium")
    monkeypatch.setenv("MOCK_MODEL", "this-employee-s-own")
    monkeypatch.setenv("MOCK_EFFORT", "xhigh")

    handler = _action_of(serve(identity))
    envelope = await handler(RecordingContext(), Ticket(ticket="sales look off"))

    assert envelope["model"] == "this-employee-s-own"
    assert envelope["effort"] == "xhigh"
