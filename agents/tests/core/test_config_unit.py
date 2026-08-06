"""Where an employee's settings come from, and which of them a ticket may move."""

import typing

import pytest

from core.config import REASONING_EFFORTS, Config, checked_effort, load


def test_the_effort_list_still_matches_the_sdk_it_was_copied_from():
    """The one thing a transcribed list cannot do for itself.

    `REASONING_EFFORTS` is written out rather than imported, because the SDK
    keeps it at an internal path and an upstream reshuffle would break every
    employee at boot. This is the alarm that trade buys: a value only one side
    knows reaches the provider as a 400 on the first turn, which arrives at a
    caller as an investigation that crashed doing real work.
    """
    from openai.types.shared.reasoning_effort import ReasoningEffort

    # `ReasoningEffort` is `Literal[...] | None`, so the literal is the first arg.
    known = typing.get_args(typing.get_args(ReasoningEffort)[0])

    assert set(REASONING_EFFORTS) == set(known), (
        "the SDK's reasoning efforts moved; update REASONING_EFFORTS to match"
    )


@pytest.mark.parametrize("given", ["HIGH", " high ", "High"])
def test_a_depth_is_read_however_it_was_typed(given):
    assert checked_effort(given) == "high"


def test_a_depth_no_provider_knows_is_refused():
    with pytest.raises(ValueError, match="effort must be one of"):
        checked_effort("ludicrous")


def test_unchosen_is_not_the_same_as_wrong():
    """Empty leaves whatever the environment already said in place."""
    assert checked_effort("") == ""


def test_an_employee_reads_its_own_settings_before_the_shared_ones(monkeypatch):
    """A campaign passes its harness and effort axes per employee. Reading only
    the shared name would hand two of them the same loop and report two
    identical cells as a comparison."""
    monkeypatch.setenv("AGENT_HARNESS", "codex")
    monkeypatch.setenv("PHILIP_HARNESS", "opencode")
    monkeypatch.setenv("AGENT_MODEL_REASONING", "medium")
    monkeypatch.setenv("PHILIP_EFFORT", "high")

    assert load("philip").harness == "opencode"
    assert load("philip").model.reasoning == "high"
    # An employee that sets nothing of its own still gets the shared value.
    assert load("angel").harness == "codex"
    assert load("angel").model.reasoning == "medium"


def test_a_ticket_moves_the_model_and_the_depth_and_nothing_else(monkeypatch):
    """The credentials, the shop's clock and the queue are the employee's
    identity, not a caller's to choose."""
    monkeypatch.setenv("AGENT_API_KEY", "the-employee-s-own")
    deployed = load()

    asked = deployed.for_call(model="another-model", effort="high")

    assert (asked.model.name, asked.model.reasoning) == ("another-model", "high")
    assert asked.shop == deployed.shop
    assert asked.queue == deployed.queue
    assert asked.model.api_key == deployed.model.api_key


def test_a_ticket_cannot_smuggle_a_depth_past_the_queue_s_edge():
    """The ticket model catches a typo arriving over the bus, but a campaign or
    a test calling this directly bypasses it — and an unvalidated depth reaches
    the provider as a 400 that reads like a crashed analyst."""
    with pytest.raises(ValueError, match="effort must be one of"):
        load().for_call(effort="ludicrous")


def test_the_new_fields_sit_last_so_positional_construction_still_works():
    """A suite outside this package builds `Config` positionally. A field
    inserted above would mis-assign every argument after it, without raising."""
    names = list(Config.__dataclass_fields__)

    assert names[-2:] == ["harness", "timeout_s"]
