"""A refused tool call must not read as a successful empty one.

Built from `runs/e_6e4022b8bdcd`, a real investigation in which opencode
refused six of fifteen bash calls — including the two that would have read
Matomo and the shop. The driver read `state["output"]`, which a refusal does
not have, so all six became empty successes. The judge saw twenty successful
reads and graded an answer built on evidence the loop was never allowed to
gather.

The fixtures below are the two shapes taken verbatim from that record, because
inventing them is how the last mapper bug survived its own unit test.
"""

from typing import Any

from core.harness.base import Kind
from core.harness.codex import _step as codex_step
from core.harness.opencode_api import steps as _steps
from core.record import from_steps

REFUSED = {
    "type": "tool",
    "tool": "bash",
    "state": {
        "status": "error",
        "input": {"command": "curl -sS $MATOMO_URL"},
        "error": "The user has specified a rule which prevents you from "
                 "using this specific tool call.",
        "time": {"start": 0, "end": 1},
    },
}
COMPLETED = {
    "type": "tool",
    "tool": "bash",
    "state": {
        "status": "completed",
        "input": {"command": "curl -sS $SHOP_API_URL"},
        "output": '{"orders":[1,2,3]}',
        "metadata": {},
        "title": "",
        "time": {"start": 0, "end": 1},
    },
}


def conversation(*parts: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"info": {"role": "assistant"}, "parts": list(parts)}]


def test_a_refusal_becomes_an_error_step_carrying_its_reason() -> None:
    """`error`, not `output` — a refused state has no `output` key at all."""
    steps = _steps(conversation(REFUSED))

    kinds = [s.kind for s in steps]
    assert kinds == [Kind.COMMAND, Kind.ERROR]
    assert "prevents you from using" in steps[1].text


def test_a_completed_call_is_untouched() -> None:
    """The ordinary path must keep working, or the fix costs more than it saves."""
    steps = _steps(conversation(COMPLETED))

    assert [s.kind for s in steps] == [Kind.COMMAND, Kind.OUTPUT]
    assert steps[1].text == '{"orders":[1,2,3]}'


def test_the_record_marks_the_refused_call_rather_than_adding_one() -> None:
    """A judge counting successful reads must not count a refusal among them.

    The error belongs to the call just recorded; a sibling entry of its own
    would both hide the failure and inflate the call count the report
    publishes.
    """
    calls = from_steps(_steps(conversation(COMPLETED, REFUSED)))

    assert len(calls) == 2
    assert [call.status for call in calls] == ["completed", "error"]
    assert "prevents you from using" in calls[1].output


def test_a_refused_call_still_says_what_it_tried_to_run() -> None:
    """The command is the evidence that the investigation was attempted at all.
    Recorded without it, a blocked read and a read never made look the same."""
    calls = from_steps(_steps(conversation(REFUSED)))

    assert calls[0].input == {"command": "curl -sS $MATOMO_URL"}


FAILED_COMMAND = {
    "type": "item.completed",
    "item": {
        "type": "command_execution",
        "command": 'curl -sS "$SHOP_API_URL/orders"',
        "aggregated_output": '{"errors":[{"code":26,"message":"unauthorized"}]}',
        "exit_code": 22,
    },
}
OK_COMMAND = {
    "type": "item.completed",
    "item": {
        "type": "command_execution",
        "command": 'curl -sS "$SHOP_API_URL/orders"',
        "aggregated_output": '{"orders":[1,2,3]}',
        "exit_code": 0,
    },
}


def test_a_command_that_exited_non_zero_is_an_error_not_an_output() -> None:
    """A 401 and a result must not be the same event downstream.

    24 of 268 completed commands in the persisted corpus exited non-zero, and
    every one was published as a plain output — so the transcript the judge
    reads counted failed reads among its successful ones.
    """
    assert codex_step(FAILED_COMMAND).kind is Kind.ERROR
    assert codex_step(OK_COMMAND).kind is Kind.OUTPUT


def test_the_failure_carries_what_the_command_printed() -> None:
    """The body is the evidence; losing it leaves an error with no reason."""
    assert "unauthorized" in codex_step(FAILED_COMMAND).text
