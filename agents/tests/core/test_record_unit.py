"""The pairing of a call with its result — the reconstruction written three times."""

import pytest

from core.harness.base import Kind, Step, Usage
from core.record import (
    MAX_OUTPUT_CHARS,
    Record,
    ToolCall,
    from_steps,
    new_id,
    read,
    runs_dir,
    usage_fields,
)


def test_a_command_is_closed_by_the_output_that_follows_it():
    calls = from_steps(
        [
            Step(kind=Kind.COMMAND, command="curl -s $SHOP_API_URL/orders"),
            Step(kind=Kind.OUTPUT, text="27 orders"),
        ]
    )
    assert len(calls) == 1
    assert calls[0].input == {"command": "curl -s $SHOP_API_URL/orders"}
    assert calls[0].output == "27 orders"
    assert calls[0].status == "completed"


def test_a_refusal_looks_like_a_refusal():
    """A command that exited non-zero is a 401, a missing binary, a denial — not
    a result. Recorded as a plain output, a `curl` that 401'd and a `curl` that
    returned the orders are the same event to the judge."""
    calls = from_steps(
        [
            Step(kind=Kind.COMMAND, command="curl -s $SHOP_API_URL/carriers"),
            Step(kind=Kind.ERROR, text="401 Unauthorized"),
        ]
    )
    assert calls[0].status == "error"
    assert calls[0].output == "401 Unauthorized"


def test_a_named_tool_keeps_structured_arguments():
    calls = from_steps(
        [
            Step(kind=Kind.TOOL, tool="shop_get", args={"resource": "deliveries"}),
            Step(kind=Kind.OUTPUT, text="4 rows"),
        ]
    )
    assert calls[0].tool == "shop_get"
    assert calls[0].input == {"resource": "deliveries"}


def test_prose_and_thinking_are_not_tool_calls():
    calls = from_steps(
        [
            Step(kind=Kind.STARTED),
            Step(kind=Kind.THINKING, text="deciding"),
            Step(kind=Kind.MESSAGE, text="Canada is zone 10."),
            Step(kind=Kind.FINISHED),
        ]
    )
    assert calls == []


def test_a_failure_before_any_call_is_still_recorded():
    """A run that died before doing anything must not be an empty list
    indistinguishable from a run that simply did nothing."""
    calls = from_steps([Step(kind=Kind.ERROR, native="turn.failed", text="429")])
    assert len(calls) == 1
    assert calls[0].status == "error"
    assert calls[0].tool == "turn.failed"


def test_an_unclosed_call_is_kept_and_does_not_claim_to_have_finished():
    """A run killed mid-command still made that command — and did not complete
    it.

    The status used to default to `completed`, so a call nothing ever closed was
    recorded as one that succeeded: silently, and in the flattering direction. A
    grader counting what an investigation managed to read counted work that
    never returned. This assertion is the whole reason the default moved.
    """
    calls = from_steps([Step(kind=Kind.COMMAND, command="sleep 600")])

    assert len(calls) == 1
    assert calls[0].output == ""
    assert calls[0].status == "pending"


def test_a_silent_success_closes_its_own_call():
    """A command can succeed with nothing on stdout — a `mkdir`, a grep that
    matched nothing. Keyed on output rather than on phase, its result step was
    never emitted and the record opened a second call nothing closed: two
    entries for one command, one of them a phantom."""
    calls = from_steps(
        [
            Step(kind=Kind.COMMAND, command="mkdir data"),
            Step(kind=Kind.OUTPUT, text=""),
        ]
    )

    assert len(calls) == 1
    assert calls[0].status == "completed"


def test_a_huge_return_is_clipped_but_its_true_size_is_kept():
    """The size handed back to the model is what a later turn resends, and it is
    not the size stored here."""
    calls = from_steps(
        [
            Step(kind=Kind.COMMAND, command="cat big.json"),
            Step(kind=Kind.OUTPUT, text="x" * (MAX_OUTPUT_CHARS * 3)),
        ]
    )
    assert len(calls[0].output) == MAX_OUTPUT_CHARS
    assert calls[0].output_chars == MAX_OUTPUT_CHARS * 3


def test_latency_survives_into_the_record():
    """The difference between 'the run took ten minutes' and 'the log store took
    nine of them'."""
    calls = from_steps(
        [
            Step(kind=Kind.TOOL, tool="logs_query"),
            Step(kind=Kind.OUTPUT, text="…", duration_ms=9_100),
        ]
    )
    assert calls[0].duration_ms == 9_100


def test_a_run_id_carries_the_name_of_whoever_earned_it():
    """Two agents once both minted `i_…` into one transcript directory, so whose
    evidence a file held was decided by luck."""
    assert new_id("angel").startswith("angel_")
    assert new_id("angel") != new_id("angel")


def test_the_transcript_directory_is_read_per_call_not_at_import(monkeypatch, tmp_path):
    """A campaign sets it inside a function, after this module was imported."""
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "elsewhere"))
    assert runs_dir() == tmp_path / "elsewhere"


def test_a_record_round_trips(tmp_path):
    written = Record(
        run_id="mock_1", agent="mock", model="a-model", harness="mock",
        status="completed", calls=[ToolCall(tool="shop_get", output="4 rows")],
        output={"detected": "nothing"},
    )
    path = written.write(tmp_path)
    assert read(path).calls[0].tool == "shop_get"


def test_a_record_from_a_shape_this_code_does_not_know_is_refused(tmp_path):
    """Silently scoring an unrecognised shape is how a grader reports a confident
    zero about a run it could not read — which has happened twice."""
    path = tmp_path / "mock_1.record.json"
    path.write_text('{"run_id": "mock_1", "version": 99}')
    with pytest.raises(ValueError, match="record version 99"):
        read(path)


def test_usage_flattens_to_the_keys_an_envelope_carries():
    flat = usage_fields(Usage(input_tokens=10, reasoning_tokens=3))
    assert flat["input_tokens"] == 10
    assert flat["reasoning_tokens"] == 3
    assert flat["cost"] is None


def test_two_calls_in_flight_together_keep_their_own_results():
    """The pairing that positional matching gets wrong.

    One loop runs a turn's calls concurrently and emits each result as it
    completes, so the second call can answer first. Paired by position, the
    slower call is recorded with no output at all and the faster result is
    attributed to a call nobody made — and both figures look entirely legal.
    """
    calls = from_steps(
        [
            Step(kind=Kind.TOOL, tool="logs_query", call_id="a"),
            Step(kind=Kind.TOOL, tool="shop_get", call_id="b"),
            # `shop_get` returns first: it was the quick one.
            Step(kind=Kind.OUTPUT, tool="shop_get", text="27 orders", call_id="b"),
            Step(kind=Kind.OUTPUT, tool="logs_query", text="9s of log", call_id="a"),
        ]
    )
    by_tool = {call.tool: call for call in calls}

    assert len(calls) == 2
    assert by_tool["shop_get"].output == "27 orders"
    assert by_tool["logs_query"].output == "9s of log"


def test_a_refusal_finds_its_own_call_among_several():
    """The rejection column decides how hard a run had to fight. Attributed to
    the wrong call it is still a rejection, but the tool it names is innocent."""
    calls = from_steps(
        [
            Step(kind=Kind.TOOL, tool="feed_read_file", call_id="a"),
            Step(kind=Kind.TOOL, tool="shop_get", call_id="b"),
            Step(kind=Kind.OUTPUT, tool="shop_get", text="ok", call_id="b"),
            Step(kind=Kind.ERROR, tool="feed_read_file", text="denied", call_id="a"),
        ]
    )
    by_tool = {call.tool: call for call in calls}

    assert by_tool["feed_read_file"].status == "error"
    assert by_tool["shop_get"].status == "completed"


def test_a_loop_that_reports_no_id_still_pairs_by_position():
    """codex and opencode are strictly sequential, so position is sound there —
    the fallback is correct rather than merely tolerated."""
    calls = from_steps(
        [
            Step(kind=Kind.COMMAND, command="curl one"),
            Step(kind=Kind.OUTPUT, text="first"),
            Step(kind=Kind.COMMAND, command="curl two"),
            Step(kind=Kind.OUTPUT, text="second"),
        ]
    )
    assert [call.output for call in calls] == ["first", "second"]
