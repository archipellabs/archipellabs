"""Does a skill actually get Ethan into a system?

One test per flow, and each asks for **a single fact that cannot be answered
without the skill for that system**. Not a plausible answer, not a well-shaped
one: a specific value that only exists inside the company.

That is the whole design. A functional test that asks "is anything wrong?"
grades prose. A functional test that asks how many order states the shop
defines has one right answer, and getting it means the loop found the skill,
read it, authenticated, chose an endpoint and parsed a reply. Every link in the
chain is proven by one number.

These are slow — a model turn each — and they need the stack up. Marked
`functional` and deselected by default; run them with `-m functional`.

They are also **not** a measure of the analyst. When one fails, the first
suspect is the skill: a system these cannot reach is a system documented badly,
which is the finding the lab is built to produce.
"""

import dataclasses
import os
import pathlib
import subprocess

import pytest

from core import load
from core.harness import desk
from roles.ethan.identity import AGENT, DESK, build

pytestmark = pytest.mark.functional


@pytest.fixture(params=["codex", "opencode"])
def harness(request: pytest.FixtureRequest) -> str:
    """Every skill test runs against both loops.

    Not `ETHAN_HARNESS`, which ran whichever one happened to be configured and
    left the other unexercised. opencode's model call broke and stayed broken
    through a full day of work because the suite was green on codex and nobody
    ran it the other way; the campaigns that did use opencode exercised a
    different entry point and passed. A skill is a claim about a system, and it
    has to hold under both loops or it is a claim about one of them.
    """
    return str(request.param)


def ask(question: str, harness_name: str) -> dict[str, str]:
    """One investigation through the named harness, answer returned.

    Built through `src.identity`, which is the one place that knows Ethan has two
    loops. Reaching into `core.harness.codex` here would work and would be
    a second such place — the shape the mapping in `identity` exists to stop.
    """
    import asyncio
    import tempfile

    harness = build(dataclasses.replace(load(AGENT), harness=harness_name))
    with tempfile.TemporaryDirectory() as scratch:
        workdir = pathlib.Path(scratch)
        desk.prepare(DESK, workdir)
        outcome = asyncio.run(harness.investigate(question, workdir))
    assert not outcome.error, outcome.error
    return outcome.answer


@pytest.fixture(scope="session", autouse=True)
def stack_is_up() -> None:
    """Skip rather than fail when the company is not running.

    A red suite because Docker is down says nothing about the skills, and a
    test that cannot tell those apart trains you to ignore it.
    """
    if not os.environ.get("SHOP_API_URL"):
        pytest.skip("no company in the environment (source the agent's .env)")


def test_the_shop_skill_reaches_the_shop(harness: str) -> None:
    """State id 2 is `Payment accepted`. Reaching it needs the whole skill:
    basic auth with the key as username, `output_format=JSON`, and the
    `order_states` resource rather than a guessed path."""
    answer = ask(
        "Using the shop, what is the exact name of order state id 2? "
        "Put that name verbatim in the summary field.",
        harness,
    )

    assert "payment accepted" in answer["summary"].lower()


def test_the_analytics_skill_reaches_matomo(harness: str) -> None:
    """Matomo has no spec and must be asked to describe itself. A loop that
    guessed REST paths finds nothing; one that read the skill calls
    `API.getReportMetadata` and gets a list back."""
    answer = ask(
        "Using analytics, call the method that makes Matomo describe its own "
        "reports, and put the number of reports it returned in the summary field.",
        harness,
    )

    assert any(char.isdigit() for char in answer["summary"])


def test_the_logs_skill_reaches_loki(harness: str) -> None:
    """Label discovery before querying, which is the skill's main point: a
    selector naming a label that does not exist returns empty, and empty is
    indistinguishable from a service that logged nothing.

    This test first asked for the values of `container`, and the run correctly
    answered that there are none — this deployment labels by `service`. The
    agent was right and the skill was wrong, which is the direction these tests
    are meant to catch."""
    answer = ask(
        "Using the logs system, list every label that exists, then list the "
        "values of the one that names the services. Put them in the summary.",
        harness,
    )

    assert "prestashop" in answer["summary"].lower()


def test_the_feed_skill_reaches_the_erp_drop(harness: str) -> None:
    """No HTTP, no contract, and the only skill whose subject is an absence."""
    answer = ask(
        "Using the ERP feed, list the file names it holds. "
        "Put them in the summary field.",
        harness,
    )

    assert ".csv" in answer["summary"].lower()


def test_the_desk_carries_what_the_brief_promises() -> None:
    """Cheap, and it catches the failure that would make every test above fail
    for one reason: the desk never arriving in the working directory.

    It no longer looks for an OpenAPI file. That file was dropped once the shop
    was found to describe itself: the API root lists resources with the calling
    key's own permissions, which a generated document cannot do. What is checked
    now is that the brief, one skill per system, and the company's CA are all
    there, since a missing CA breaks every HTTPS command with an error the agent
    reads as an unreachable system.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        desk.prepare(DESK, root)

        assert (root / "AGENTS.md").is_file()
        assert (root / desk.CA_FILE).is_file()
        skills = {p.name for p in (root / ".agents/skills").iterdir()}
        assert skills == {
            "shop-webservice",
            "analytics-matomo",
            "logs-loki",
            "erp-feed",
        }


def test_both_harnesses_are_installed() -> None:
    """A missing binary fails as a timeout deep inside a driver otherwise."""
    for binary in ("codex", "opencode"):
        assert subprocess.run(
            ["which", binary], capture_output=True
        ).returncode == 0, f"{binary} is not on PATH"
