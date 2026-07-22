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
