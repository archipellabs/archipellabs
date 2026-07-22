"""Read-only async access to the activity database.

The portal is a *separate consumer* of the shared Postgres: it queries the schema
the simulator's Alembic migrations own, but never imports the simulator's code. So
this is deliberately thin — a Core connection for aggregate SQL, no ORM models.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)


async def get_connection() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency yielding a short-lived read connection."""
    async with engine.connect() as conn:
        yield conn
