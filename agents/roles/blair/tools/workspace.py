"""Scratch owned by one investigation.

Names written by a previous run are hypotheses in disguise.  A context-local
workspace keeps tables and downloaded logs isolated even when the queue process
serves many tickets over its lifetime.
"""

import contextvars
import os
import pathlib

ROOT = pathlib.Path(
    os.getenv("BLAIR_WORKSPACE_DIR")
    or pathlib.Path(__file__).resolve().parents[2] / "workspaces"
)

_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "blair_run", default=None
)


def use(run_id: str) -> contextvars.Token[str | None]:
    return _RUN.set(run_id)


def release(token: contextvars.Token[str | None]) -> None:
    _RUN.reset(token)


def root() -> pathlib.Path:
    run_id = _RUN.get()
    return ROOT / run_id if run_id else ROOT / "interactive"


def tables() -> pathlib.Path:
    return root() / "tables"


def logs() -> pathlib.Path:
    return root() / "logs"
