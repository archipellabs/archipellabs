"""The entry point a campaign discovers.

`campaign.EMPLOYEES` hires whoever has this file, and calls `run_investigation`
with a config and a ticket. Shipping it here puts a free employee in the roster,
which is what makes the runner, the worker and the grader's record reader
testable end to end without a model — nothing else in this repository could do
that.

A campaign only runs the agents it is asked to run, so being hireable costs
nothing.
"""

from typing import Any

from core import Config, investigate
from roles.mock.identity import IDENTITY


async def run_investigation(cfg: Config, ticket: str) -> dict[str, Any]:
    """Two positional arguments and a dict back — the runner's whole contract."""
    return await investigate(IDENTITY, cfg, ticket)
