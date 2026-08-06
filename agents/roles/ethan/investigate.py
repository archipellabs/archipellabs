"""The filename the lab hires by.

The campaign runner hires by filename: it discovers employees by looking for
`investigate.py` in each directory under `roles/`, so this file has to sit
here under this name. It used to look for `src/investigate.py`, back when
each employee was its own project.

It used to be a shim over a `campaign_adapter/` package — a bridge to somebody
else's launcher, kept in its own folder because it was written to be deleted.
It has been: the campaign and the bus now reach the same `core.investigate`
through the same envelope, so the bridge had nothing left to translate. Ethan's
other interface is `ethan.investigate` on the bus, and it is this function with a
narrator attached.
"""

from typing import Any

from core import Config, investigate
from roles.ethan.identity import IDENTITY, routable


async def run_investigation(cfg: Config, ticket: str) -> dict[str, Any]:
    """Two positional arguments and a dict back — the runner's whole contract.

    The base-URL guard runs here and nowhere else. This is the one caller that
    names an endpoint and then labels a result row with it; a ticket arriving on
    the bus names none.
    """
    routable(cfg)
    return await investigate(IDENTITY, cfg, ticket)


__all__ = ["run_investigation"]
