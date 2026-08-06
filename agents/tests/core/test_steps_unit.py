"""The vocabulary boundary.

The app publishes what a loop did without knowing which loop did it. That only
holds if two things are true, and both are asserted here: each driver maps its
vendor's words into the standard ones, and nothing downstream ever sees the
vendor's word.

Written as unit tests because neither needs a running harness. A translator is
a pure function, and the useful thing to check about it is what it does with
input it was not taught about.
"""

from core.harness.base import Kind, Step
from core.harness.codex import _step as codex_step
from core.harness.opencode_api import steps as opencode_conversation
from core.run import as_event


def test_codex_items_become_standard_kinds() -> None:
    """The fixtures below use `item["type"]`, which is the real key.

    They used to say `item_type`, which is not, and the mapper read the same
    wrong key: test and code agreed, every assertion passed, and every event on
    the bus came out as `other`. A fixture written from the same guess as the
    code proves the guess is consistent, not that it is right.
    """
    command = codex_step(
        {"type": "item.started", "item": {"type": "command_execution",
                                          "command": "curl -sS x"}}
    )
    message = codex_step(
        {"type": "item.completed", "item": {"type": "agent_message",
                                            "text": "done"}}
    )

    assert command.kind is Kind.COMMAND
    assert message.kind is Kind.MESSAGE


def test_a_finished_command_is_its_own_output_step() -> None:
    """The command and what it returned are two things a watcher wants apart."""
    step = codex_step(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "ls",
                "aggregated_output": "carriers.csv",
            },
        }
    )

    assert step.kind is Kind.OUTPUT
    assert step.text == "carriers.csv"


def test_codex_names_its_non_shell_work_by_item_type() -> None:
    """It carries no argument shape stable enough to fill `args` from, so the
    type is the tool's name and the arguments stay empty rather than invented.
    Without this every one of them reached a record called `tool`."""
    step = codex_step({"type": "item.completed", "item": {"type": "file_change"}})

    assert step.kind is Kind.TOOL
    assert step.tool == "file_change"
    assert step.args == {}
    assert step.command == ""


def test_the_shell_is_the_one_opencode_tool_that_carries_a_command() -> None:
    """`bash` belongs in `command`, where the rest of the package looks for one —
    which skill a run opened is inferred from it."""
    call, _returned = opencode_conversation(
        [
            {
                "info": {"role": "assistant"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {
                            "status": "completed",
                            "input": {"command": "cat .agents/skills/x/SKILL.md"},
                            "output": "…",
                            "time": {"start": 1000, "end": 1750},
                        },
                    }
                ],
            }
        ]
    )

    assert call.kind is Kind.COMMAND
    assert call.tool == "bash"
    assert call.command == "cat .agents/skills/x/SKILL.md"
    assert call.duration_ms == 750


def test_an_unknown_type_still_arrives() -> None:
    """A harness that grows a step type should show up in the stream, not be
    dropped by a translator nobody has taught about it yet."""
    step = codex_step({"type": "turn.interrupted_by_a_new_feature"})

    assert step.kind is Kind.OTHER
    assert step.native == "turn.interrupted_by_a_new_feature"


def test_the_event_never_carries_the_vendor_s_word() -> None:
    """The boundary itself. A subscriber that could read `item.completed` could
    branch on which harness ran, and the harness is the variable under test."""
    step = Step(kind=Kind.COMMAND, native="item.completed", command="ls")

    published = as_event(step)

    assert published["kind"] == "command"
    assert "native" not in published
    assert "item.completed" not in str(published)


def test_codex_non_shell_work_arrives_finished_rather_than_open() -> None:
    """A `file_change` is one event carrying both that the call was made and
    that it finished.

    Mapped to a single `TOOL` step it opened a call in the record that nothing
    ever closed, and every one was filed unfinished — four of twenty-five calls
    in a real run, all of them work codex had in fact completed. A shell command
    gets two events and so two steps; this gives the others the same shape.
    """
    from core.harness.codex import _steps
    from core.record import from_steps

    produced = _steps({"type": "item.completed", "item": {"type": "file_change"}})

    assert [step.kind for step in produced] == [Kind.TOOL, Kind.OUTPUT]

    (recorded,) = from_steps(produced)
    assert recorded.tool == "file_change"
    assert recorded.status == "completed"


def test_a_command_starting_is_still_one_open_call() -> None:
    """`item.started` is a call beginning and nothing else. Closing it here
    would report every command finished the instant it was launched."""
    from core.harness.codex import _steps

    produced = _steps(
        {"type": "item.started", "item": {"type": "command_execution",
                                          "command": "sleep 600"}}
    )

    assert [step.kind for step in produced] == [Kind.COMMAND]
