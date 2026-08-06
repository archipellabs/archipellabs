"""One scratch directory per investigation.

Datasets and downloaded logs went to two shared folders, so every run opened with
the previous run's files already in view. `data_datasets()` listed names like
`affected_addresses`, `complaint_carts`, `recent_carts` — which are not data, they
are **the previous investigator's hypotheses stated as nouns**. A run could read
the conclusion of the run before it and never know it had.

That is worse than a tidiness problem. It makes two runs of a campaign not
independent, so a rate built from them measures something other than what it
claims, and it hands a model the one thing the lab exists to withhold: where to
look.

A ContextVar rather than an environment variable, because the queue service runs
many investigations in one process and an env var mutated per run is a race
waiting for the day `max_slots` stops being 1.

**No active run means the shared directory**, which is what an interactive
`uv run python -m src` and every unit test get. Isolation is a property of a
campaign, not a thing to make a developer's ad-hoc run harder to inspect.
"""

import contextvars
import os
import pathlib
import re

ROOT = pathlib.Path(
    os.getenv("AGENT_WORKSPACE_DIR")
    or pathlib.Path(__file__).resolve().parents[2] / "workspaces"
)

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_run_id", default=None
)


def use(run_id: str) -> contextvars.Token[str | None]:
    """Scope the following work to one run. Pass the token back to `release`."""
    return _current.set(run_id)


def release(token: contextvars.Token[str | None]) -> None:
    _current.reset(token)


def current() -> str | None:
    return _current.get()


def _dir(kind: str) -> pathlib.Path | None:
    """This run's directory for `kind`, or nothing when no run is active."""
    run_id = _current.get()
    if not run_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)
    return ROOT / safe / kind


def datasets() -> pathlib.Path | None:
    return _dir("datasets")


def logs() -> pathlib.Path | None:
    return _dir("logs")
