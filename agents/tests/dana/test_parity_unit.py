"""Dana exists to hold the tools constant while the loop changes.

    angel   = our loop  + these tools
    dana    = opencode  + these tools      ← the only difference is the loop
    charlie = opencode  + thinner tools

If Dana's tool surface drifts from Angel's, that sentence stops being true and a
campaign comparing them silently measures two things again. This file is the
guard, and it compares against Angel's real registrations rather than a list
kept here, which would drift in its own way.
"""

import pathlib
import re

import pytest

from core.brief import BRIEF, JSON_VERDICT
from core.harness.opencode_mcp import SYSTEM_PROMPT
from roles.dana import mcp_server

ROLES = pathlib.Path(__file__).resolve().parents[2] / "roles"

# Angel's loop needs these; they are not reads of the company.
#
# `thought` is a scratchpad for models that emit reasoning as a tool call
# whether or not one is offered. opencode has its own reasoning channel and
# reports the tokens separately, so giving Dana a `thought` tool would add a
# call Angel makes and Dana never needs — a difference in the wrong direction.
#
# `register` is the function the tool closures are declared inside, since Angel's
# loop moved to `core`. It replaces `build`, which used to hold them and no
# longer exists. Both are caught by the pattern below because `\s` matches the
# newline of a blank line, so a module-level `def` is picked up along with the
# indented ones — which is why this list exists at all.
NOT_TOOLS = {"register", "thought"}


def _angel_tools() -> set[str]:
    source = (ROLES / "angel" / "agent.py").read_text()
    return set(re.findall(r"^\s+(?:async )?def ([a-z_]+)\(", source, re.M)) - NOT_TOOLS


def _dana_tools() -> set[str]:
    source = (ROLES / "dana" / "mcp_server.py").read_text()
    found = set(re.findall(r"^(?:async )?def ([a-z][a-z_]*)\(", source, re.M))
    return found - {"main", "cfg"}


def test_dana_offers_every_tool_angel_does():
    missing = _angel_tools() - _dana_tools()

    assert not missing, f"Angel can reach these and Dana cannot: {sorted(missing)}"


def test_dana_offers_nothing_angel_lacks():
    """A tool Dana has and Angel does not would make it the better-equipped
    agent rather than the same agent with another loop."""
    extra = _dana_tools() - _angel_tools()

    assert not extra, f"Dana has tools Angel does not: {sorted(extra)}"


def test_the_tools_are_angel_s_own_code_not_a_reimplementation():
    """Copied verbatim. Reimplemented, every fix Angel earned — the completeness
    envelope, the client-side sort, the translated refusals — would have to be
    earned again, and the two would diverge exactly where it matters.

    **Discovered, not listed.** A hand-written list of four covered four of the
    seven modules while this docstring and the README both said the package was
    copied whole; `analytics.py`, `feed.py` and `workspace.py` — 285 lines —
    could drift with nothing to notice. This is the control against which the
    loop is the only intended difference, so a guard that covers most of it is
    the wrong shape.
    """
    theirs = sorted(p.name for p in (ROLES / "angel" / "tools").glob("*.py"))
    ours = sorted(p.name for p in (ROLES / "dana" / "tools").glob("*.py"))

    assert theirs == ours, "the two toolsets do not hold the same modules"
    assert len(theirs) >= 7, "suspiciously few tool modules found"

    for module in theirs:
        angel = (ROLES / "angel" / "tools" / module).read_text()
        dana = (ROLES / "dana" / "tools" / module).read_text()

        # Byte-identical apart from the owner's own name. These files used to
        # match exactly, because both said `from src.tools import …` and `src`
        # meant whichever project you were standing in. One project cannot have
        # seven packages called `src`, so each module now names its owner — and
        # that one word is the only difference this comparison forgives.
        assert angel.replace("roles.angel", "@") == dana.replace(
            "roles.dana", "@"
        ), f"{module} has drifted from Angel's"


def test_the_brief_is_the_shared_one_plus_only_the_output_shape():
    """Four employees carrying four wordings would compare wordings. The JSON
    instruction is the one difference the harness forces: it says how to reply,
    never what to look for.

    Composed by the harness rather than here — enforcing the answer is the
    harness's job, and Dana and Charlie appending their own would be two
    employees a campaign could no longer compare."""
    assert SYSTEM_PROMPT == BRIEF + JSON_VERDICT


@pytest.mark.parametrize(
    "giveaway", ["carrier", "shipping", "CSV", "zone", "delivery", "reconcil"]
)
def test_the_brief_does_not_name_the_mechanism_of_any_incident(giveaway):
    """An earlier brief explained that a carrier needs a price for a customer's
    market and that master data arrives as CSVs on a file drop — the mechanism
    AND the location of the incident being staged. The model reported both,
    with high confidence, having queried neither.

    Naming the two markets is not the same thing and stays: which countries the
    company sells to is what the company IS, and an analyst who cannot know
    there are two markets is not being tested on investigation. The line is
    between describing the business and describing a failure in it.
    """
    assert giveaway.lower() not in BRIEF.lower()


def test_every_system_is_on_the_map():
    """The map is fair — the territory is the job. Without it an agent cannot
    know the ERP feed exists at all, which is not a test of investigation."""
    for system in ("the shop", "web analytics", "the logs", "the ERP feed"):
        assert system in BRIEF


def test_the_mcp_server_exposes_the_tools_under_one_namespace():
    """opencode prefixes them `archipel_`, which the grader strips. A second
    server name would be invisible to it."""
    assert mcp_server.server.name == "archipel"
