"""The filename the lab hires by.

`research/lab/campaign.py` discovers employees by looking for `src/investigate.py`
in each agent directory, so this file has to sit here under this name.

It used to be the investigation itself — a live event handler, a crash path and a
verdict envelope assembled by hand, the same decisions as Angel's taken slightly
differently, which is how the two lineages drifted. Both are
`core.investigate` now. Blair's other interface is `blair.investigate` on
the bus, and it is this function with a narrator attached.
"""

from typing import Any

from core import Config, investigate
from roles.blair.identity import IDENTITY


async def run_investigation(cfg: Config, ticket: str) -> dict[str, Any]:
    """Two positional arguments and a dict back — the runner's whole contract."""
    return await investigate(IDENTITY, cfg, ticket)


__all__ = ["run_investigation"]
