"""The free employee, checked so the thing everything else trusts is trustworthy."""

import pathlib
import time

import pytest

from core import Answer, Kind, investigate
from core.config import load
from core.mock import ANSWER, SCRIPT, MockHarness
from roles.mock.identity import IDENTITY


@pytest.fixture(autouse=True)
def runs_here(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path / "runs"))


@pytest.fixture
def cfg():
    return load(IDENTITY.name)


async def test_it_answers_the_same_thing_every_time(cfg):
    """A mock that varied would be a second thing under test: a failing
    assertion could not tell the code apart from the double."""
    first = await investigate(IDENTITY, cfg, "sales look off")
    second = await investigate(IDENTITY, cfg, "something else entirely")

    assert first["answer"] == second["answer"] == ANSWER.model_dump()


async def test_the_answer_is_complete_under_the_contract(cfg):
    """A partial answer would make every consumer's happy path untested."""
    envelope = await investigate(IDENTITY, cfg, "sales look off")

    assert envelope["status"] == "completed"
    assert all(envelope["answer"][field] for field in Answer.model_fields)
    assert envelope["answer"]["findings"]


async def test_a_step_count_is_honoured(cfg):
    harness = MockHarness(steps=3)
    outcome = await harness.investigate("t", pathlib.Path("."))

    # The count is the scripted steps; the boundaries are extra by definition.
    assert len(outcome.steps) == 3 + 2
    assert outcome.steps[0].kind is Kind.STARTED
    assert outcome.steps[-1].kind is Kind.FINISHED


async def test_the_script_cycles_rather_than_repeating_one_step(cfg):
    """One glyph over and over would leave a reader's rendering untested."""
    outcome = await MockHarness(steps=len(SCRIPT)).investigate("t", pathlib.Path("."))
    assert len({step.kind for step in outcome.steps}) > 3


async def test_no_delay_means_no_sleep():
    """A unit test must not sleep. Zero is the default for exactly that."""
    began = time.monotonic()
    await MockHarness(steps=20).investigate("t", pathlib.Path("."))
    assert time.monotonic() - began < 0.1


async def test_a_delay_actually_spaces_the_steps():
    began = time.monotonic()
    await MockHarness(steps=3, delay_s=0.05).investigate("t", pathlib.Path("."))
    assert time.monotonic() - began >= 0.05


async def test_the_failure_path_can_be_staged(cfg):
    outcome = await MockHarness(error="the server refused").investigate(
        "t", pathlib.Path(".")
    )
    assert outcome.error == "the server refused"
    assert outcome.answer is None
    assert outcome.steps, "a loop that died mid-way still said what it was doing"


async def test_the_campaign_s_entry_point_returns_an_envelope(cfg):
    """Two positional arguments and a dict back — the runner's whole contract."""
    from roles.mock.investigate import run_investigation

    envelope = await run_investigation(cfg, "sales look off")
    assert envelope["agent"] == "mock"
    assert pathlib.Path(envelope["transcript"]).is_file()
