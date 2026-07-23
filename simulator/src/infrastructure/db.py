"""Shared database infrastructure — the declarative base + connection plumbing.

Generic and flow-agnostic on purpose, and outside the flows: more than one flow
will persist over time, and Alembic needs a single `Base.metadata` spanning every
entity to run one migration history. Each flow's entities inherit from this `Base`;
each flow builds its own engine/session from these factories.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The one declarative base every flow's entities inherit from."""


def make_engine(dsn: str) -> AsyncEngine:
    return create_async_engine(dsn, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def run_migrations() -> None:
    """Upgrade the activity DB to the latest schema, then return.

    Idempotent (a no-op once the DB is at head) and run synchronously at startup —
    before the async app boots — so a fresh database or a newly added migration
    needs only an app (re)start, not a separate migration step. Alembic reads the
    DB URL from ``migrations/env.py`` (a single, env-driven source of truth).
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]  # the simulator/ project root
    cfg = Config(str(root / "alembic.ini"))
    # Absolute path so it resolves no matter the working directory (container /app
    # or a local run from simulator/).
    cfg.set_main_option("script_location", str(root / "migrations"))
    # Embedded run: skip alembic's fileConfig (env.py reads this flag) so it does
    # not hijack the app's logging — it would disable existing loggers and hold
    # root at WARNING, muting the runtime's INFO output past the migration line.
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, "head")
