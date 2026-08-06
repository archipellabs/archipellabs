"""The filename the lab hires by.

`research/lab/campaign.py` discovers employees by looking for `src/investigate.py`
in each agent directory, so this file has to sit here under this name.

It used to be the investigation itself: a live event handler, a crash path, a
verdict envelope assembled by hand — and byte-for-byte the same decisions in
Blair, taken slightly differently. Both are `core.investigate` now, so a
fix to either is a fix to both. Angel's other interface is `angel.investigate` on
the bus, and it is this function with a narrator attached.
"""

from typing import Any

from core import Config, investigate
from roles.angel.identity import IDENTITY


async def run_investigation(cfg: Config, ticket: str) -> dict[str, Any]:
    """Two positional arguments and a dict back — the runner's whole contract.

    No base-URL guard, unlike the desk-driven employees: Angel's provider is
    built from the endpoint it is handed, so a campaign naming one is naming the
    one that will be called. See `identity`.
    """
    return await investigate(IDENTITY, cfg, ticket)


__all__ = ["run_investigation"]
