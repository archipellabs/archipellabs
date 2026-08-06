"""The filename the lab hires by.

The campaign runner hires by filename: it discovers employees by looking for
`investigate.py` in each directory under `roles/`, so this file has to sit
here under this name. It used to look for `src/investigate.py`, back when
each employee was its own project.

It used to be the whole employee: a driver for `opencode serve`, a converter from
its conversation to the lab's record, an envelope built by hand — 440 lines, and
byte-identical to the file next door in Charlie. Both are `core` now, so a
fix to either is a fix to both. Dana's other interface is `dana.investigate` on
the bus, and it is this function with a narrator attached.
"""

from typing import Any

from core import Config, investigate
from roles.dana.identity import IDENTITY


async def run_investigation(cfg: Config, ticket: str) -> dict[str, Any]:
    """Two positional arguments and a dict back — the runner's whole contract.

    No base-URL guard, unlike the desk-driven employees: Dana's provider is built
    from the endpoint it is handed, so a campaign naming one is naming the one
    that will be called. See `identity`.
    """
    return await investigate(IDENTITY, cfg, ticket)


__all__ = ["run_investigation"]
