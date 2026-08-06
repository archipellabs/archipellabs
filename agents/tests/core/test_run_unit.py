"""The one code path, exercised with the loop taken out.

Every assertion here was previously reachable only by spending a model call, and
several of these behaviours were first observed failing in production.
"""

import pathlib

import pytest

from core import mock, run
from core.config import load
from core.contract import Answer
from core.harness.base import Identity, Kind, Outcome, Step
from core.record import read
from core.run import as_event


@pytest.fixture(autouse=True)
def runs_here(tmp_path, monkeypatch):
    """Every run in this module writes its record under the test's own tmp."""
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "runs"))


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_NAME", "a-model")
    monkeypatch.setenv("AGENT_MODEL_REASONING", "low")
    return load()


class Recorder:
    """A narrator that keeps what it was told, in order."""

    def __init__(self) -> None:
        self.said: list[tuple[str, dict]] = []

    async def started(self, **fields):
        self.said.append(("started", fields))

    async def step(self, **fields):
        self.said.append(("step", fields))

    async def finished(self, **fields):
        self.said.append(("finished", fields))

    def of(self, boundary: str) -> list[dict]:
        return [fields for name, fields in self.said if name == boundary]


def an_identity(**settings) -> Identity:
    return Identity("mock", mock.build(**settings))


async def test_a_completed_run_carries_the_whole_envelope(cfg):
    envelope = await run.investigate(an_identity(), cfg, "sales look off")

    assert envelope["status"] == "completed"
    assert envelope["agent"] == "mock"
    assert envelope["run_id"].startswith("mock_")
    assert envelope["harness"] == "mock"
    assert envelope["model"] == "a-model"
    assert envelope["effort"] == "low"
    assert pathlib.Path(envelope["transcript"]).is_file()


async def test_the_verdict_is_nested_and_the_accounting_is_flat(cfg):
    """Together in one dictionary they were the same thing, and a page rendering
    the answer showed `cache_read_tokens` as a finding."""
    envelope = await run.investigate(an_identity(), cfg, "sales look off")

    assert set(envelope["answer"]) == set(Answer.model_fields)
    assert envelope["input_tokens"] == mock.USAGE.input_tokens
    assert envelope["reasoning_tokens"] == mock.USAGE.reasoning_tokens
    assert "input_tokens" not in envelope["answer"]


async def test_every_kind_survives_the_trip_to_a_subscriber(cfg):
    heard = Recorder()
    await run.investigate(an_identity(), cfg, "sales look off", narrator=heard)

    kinds = {fields["kind"] for fields in heard.of("step")}
    assert {"thinking", "command", "output", "tool", "message"} <= kinds


async def test_the_vendor_s_word_never_reaches_a_subscriber(cfg):
    """An event carrying `mock.thinking` would let a subscriber branch on which
    loop ran, and the loop is what this lab keeps swapping."""
    heard = Recorder()
    await run.investigate(an_identity(), cfg, "sales look off", narrator=heard)

    assert heard.of("step")
    assert not any("native" in fields for fields in heard.of("step"))


async def test_steps_are_numbered_so_a_reader_can_order_them(cfg):
    """Three topics are three Redis streams and nothing orders one before
    another."""
    heard = Recorder()
    await run.investigate(an_identity(), cfg, "sales look off", narrator=heard)

    assert [fields["n"] for fields in heard.of("step")] == list(
        range(1, len(heard.of("step")) + 1)
    )


async def test_a_named_tool_call_keeps_its_arguments(cfg):
    """Encoded into a command string and split back apart on the first space,
    they arrived as `{"command": "..."}` instead of what the model passed."""
    envelope = await run.investigate(an_identity(), cfg, "sales look off")

    calls = read(pathlib.Path(envelope["transcript"])).calls
    named = [call for call in calls if call.tool == "shop_get"]
    assert named and named[0].input["resource"] == "deliveries"


async def test_the_caller_s_reference_comes_back_on_the_envelope(cfg):
    envelope = await run.investigate(
        an_identity(), cfg, "sales look off", reference="req-42"
    )
    assert envelope["reference"] == "req-42"


async def test_the_finished_envelope_does_not_collide_with_its_own_fields(cfg):
    """The envelope is splatted into the narrator, and a duplicate keyword is a
    TypeError raised at binding time — the bug that killed a run at its last
    step after ten minutes of work."""
    heard = Recorder()
    await run.investigate(an_identity(), cfg, "sales look off", narrator=heard)

    finished = heard.of("finished")
    assert len(finished) == 1
    assert finished[0]["run_id"] and finished[0]["status"] == "completed"


async def test_the_start_is_announced_before_any_step(cfg):
    """A subscriber joining on `started` must not have missed the opening
    steps — that is what a dropped connection looks like."""
    heard = Recorder()
    await run.investigate(an_identity(), cfg, "sales look off", narrator=heard)

    assert [name for name, _ in heard.said][0] == "started"
    assert [name for name, _ in heard.said][-1] == "finished"


async def test_a_narrator_that_raises_does_not_end_the_investigation(cfg):
    """The dependency runs the wrong way if a broken watcher can kill a run."""

    class Broken(Recorder):
        async def step(self, **fields):
            raise RuntimeError("the subscriber went away")

        async def finished(self, **fields):
            raise RuntimeError("and stayed away")

    envelope = await run.investigate(
        an_identity(), cfg, "sales look off", narrator=Broken()
    )
    assert envelope["status"] == "completed"


async def test_a_failing_loop_is_a_value_not_an_exception(cfg):
    envelope = await run.investigate(
        an_identity(error="opencode refused the session"), cfg, "sales look off"
    )

    assert envelope["status"] == "crashed"
    assert "refused" in envelope["error"]
    assert envelope["answer"] is None


async def test_a_failed_loop_still_records_what_it_did(cfg):
    """A loop that dies mid-way has already said what it was doing, and a record
    that forgot that is a record of nothing."""
    envelope = await run.investigate(an_identity(error="killed"), cfg, "sales look off")
    assert envelope["tool_calls"] > 0


async def test_a_loop_that_breaks_its_own_contract_is_still_a_value(cfg):
    """`Harness.investigate` must return rather than raise. One that raises
    anyway must not take the caller down with it."""

    class Exploding:
        name = "exploding"

        async def investigate(self, ticket, workdir, on_step=None):
            raise RuntimeError("no handler at all")

    envelope = await run.investigate(
        Identity("mock", lambda _cfg: Exploding()), cfg, "sales look off"
    )
    assert envelope["status"] == "crashed"
    assert "no handler at all" in envelope["error"]


async def test_an_unusable_answer_says_so_rather_than_passing(cfg):
    """Three separate checks used to do this and only one could say why."""

    class Vague:
        name = "vague"

        async def investigate(self, ticket, workdir, on_step=None):
            return Outcome(answer={"detected": "something"}, harness=self.name)

    envelope = await run.investigate(
        Identity("mock", lambda _cfg: Vague()), cfg, "sales look off"
    )
    assert envelope["status"] == "failed"
    assert "did not match the contract" in envelope["error"]


async def test_a_loop_that_cannot_be_built_is_reported_as_a_crash(cfg):
    def refuse(_cfg):
        raise ValueError("codex ignores --base-url; leave philip out")

    envelope = await run.investigate(Identity("mock", refuse), cfg, "sales look off")
    assert envelope["status"] == "crashed"
    assert "codex ignores" in envelope["error"]


async def test_two_runs_never_share_an_id(cfg):
    first = await run.investigate(an_identity(steps=1), cfg, "one")
    second = await run.investigate(an_identity(steps=1), cfg, "two")
    assert first["run_id"] != second["run_id"]


async def test_a_ticket_s_choice_does_not_leak_into_the_next_one(cfg):
    """The process outlives every ticket. A depth written onto the shared config
    would answer somebody else's question at a depth they never asked for."""
    chosen = cfg.for_call(model="another-model", effort="high")

    assert (chosen.model.name, chosen.model.reasoning) == ("another-model", "high")
    assert (cfg.model.name, cfg.model.reasoning) == ("a-model", "low")


def test_a_step_is_translated_without_its_vendor():
    event = run.as_event(
        Step(
            kind=Kind.COMMAND,
            native="item.completed",
            command="cat .agents/skills/shop-webservice/SKILL.md",
        )
    )
    assert event["kind"] == "command"
    assert event["skill"] == "shop-webservice"
    assert "native" not in event


def test_a_long_step_is_clipped_for_the_bus_not_for_the_record():
    """An event is a window, not a copy: the full step is in the record."""
    event = run.as_event(Step(kind=Kind.OUTPUT, text="x" * 5000))
    assert len(event["text"]) == run.MAX_TEXT


def test_an_unmapped_kind_arrives_as_something():
    """A loop that grows a step type should reach the stream rather than be
    dropped by a translator nobody has taught about it yet."""
    assert run.as_event(Step(kind=Kind.OTHER, native="session.compacted"))["kind"] == (
        "other"
    )


def test_an_identity_cannot_claim_another_s_action():
    with pytest.raises(ValueError, match="plain identifier"):
        Identity("angel.investigate", lambda _cfg: mock.MockHarness())


async def test_a_loop_that_cannot_be_built_still_ends_the_way_every_run_ends(cfg):
    """The failure that used to leave by a side door.

    It returned early and so skipped everything after: the caller's `reference`,
    the `started` event, the `finished` event. A watcher saw an investigation
    that never began and never ended, and the reply came back unattributable —
    all three silently, because the envelope itself looked complete.
    """

    def refuse(_cfg):
        raise ValueError("codex ignores --base-url; leave philip out")

    heard = Recorder()
    envelope = await run.investigate(
        Identity("mock", refuse), cfg, "sales look off",
        reference="req-42", narrator=heard,
    )

    assert envelope["status"] == "crashed"
    assert "codex ignores" in envelope["error"]
    assert envelope["reference"] == "req-42"
    assert len(heard.of("started")) == 1
    assert len(heard.of("finished")) == 1
    assert heard.of("finished")[0]["reference"] == "req-42"


async def test_a_run_is_priced_at_its_final_return(cfg, monkeypatch):
    """The employee prices its own run, because it is the thing that knows which
    model it ran. A portal computing this from a name and a table of its own
    would be a second table, and two tables agree only until they do not."""
    monkeypatch.setenv("AGENT_MODEL_NAME", "gpt-5.6-luna")
    envelope = await run.investigate(an_identity(), load(), "sales look off")

    # The mock spends 10 303 in, of which 6 942 cached, and 1 036 out.
    assert envelope["estimated_cost"] == 0.0021
    assert envelope.get("cost") is None, "no loop here reported a billed figure"


async def test_a_model_nobody_priced_shows_no_price_rather_than_zero(cfg, monkeypatch):
    """Unpriced is not free. A figure invented here is a figure this repository
    could publish wrong, and it has retracted one for less.

    Named after a model that does not exist rather than one that merely has no
    rate yet: this test used to point at `terra`, and it failed the moment
    `terra` was priced — correctly, but for a reason that had nothing to do with
    what it guards."""
    monkeypatch.setenv("AGENT_MODEL_NAME", "a-model-nobody-published")
    envelope = await run.investigate(an_identity(), load(), "sales look off")

    assert envelope["estimated_cost"] is None


def test_a_tool_call_publishes_what_it_was_asked_for():
    """A tool name alone says almost nothing. `shop_get` is every read this
    analyst ever makes; `shop_get(resource="deliveries")` is what it was looking
    for. The arguments were kept in the record and dropped from the event, so a
    watcher saw the shape of an investigation and never its subject."""
    event = as_event(
        Step(kind=Kind.TOOL, tool="shop_get", args={"resource": "deliveries"})
    )

    assert event["tool"] == "shop_get"
    assert event["args"] == {"resource": "deliveries"}


def test_a_huge_argument_cannot_outgrow_the_answer_it_narrates():
    """One loop's file-change arguments carry a whole patch. An event is a
    window on a step, not a copy of it — the record keeps them whole."""
    event = as_event(
        Step(kind=Kind.TOOL, tool="apply_patch", args={"diff": "x" * 5000})
    )

    assert len(event["args"]["diff"]) == run.MAX_TEXT


def test_a_call_taking_dozens_of_arguments_publishes_a_handful():
    event = as_event(
        Step(kind=Kind.TOOL, tool="wide", args={f"k{i}": i for i in range(40)})
    )

    assert len(event["args"]) == run.MAX_ARGS
