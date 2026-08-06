"""The brief promises systems; this checks the employee can actually reach them.

The inconsistency this exists for: the shared brief listed web analytics among
the systems available, and Charlie exposed no analytics tool at all. An agent
told a system exists and given no way to open it either wastes calls looking for
one or, worse, reasons as though it had checked.

The brief is shared, so it must be true for everyone who carries it. That is a
property no reader will reliably notice and a test notices every time.
"""

import re

from core.brief import BRIEF, JSON_VERDICT
from core.harness.opencode_mcp import SYSTEM_PROMPT
from roles.charlie import mcp_server

SYSTEMS = {
    "the shop": "shop_",
    "web analytics": "analytics_",
    "the logs": "logs_",
    "the ERP feed": "feed_",
}


def _tools() -> set[str]:
    return {n for n in dir(mcp_server) if not n.startswith("_")}


def test_every_system_the_brief_names_has_a_tool_behind_it():
    tools = _tools()
    for system, prefix in SYSTEMS.items():
        assert system in BRIEF, f"{system} left the brief; drop it here too"
        assert any(name.startswith(prefix) for name in tools), (
            f"the brief promises {system!r} and no {prefix}* tool exists"
        )


def test_the_brief_names_every_system_that_has_tools():
    """The other direction: a tool nobody is told about is a tool nobody uses,
    and the map is the fair half of this experiment."""
    tools = _tools()
    for prefix in {p for p in SYSTEMS.values()}:
        if any(name.startswith(prefix) for name in tools):
            system = next(s for s, p in SYSTEMS.items() if p == prefix)
            assert system in BRIEF


def test_the_brief_is_the_shared_one_plus_only_the_output_shape():
    """Composed by the harness rather than here, because enforcing the answer is
    the harness's job: pydantic-ai makes the verdict a tool the model must
    satisfy and opencode cannot. Still asserted from this side — the brief is
    the easiest thing in the system to change by accident, and a campaign
    comparing two employees on it would be comparing wordings."""
    assert SYSTEM_PROMPT == BRIEF + JSON_VERDICT


def test_the_brief_carries_no_worked_example():
    """A worked example is the staged incident written into the prompt. Several
    incidents are meant to run against these employees."""
    assert not re.search(r"\bfor example\b|\be\.g\.\b", BRIEF, re.I)
