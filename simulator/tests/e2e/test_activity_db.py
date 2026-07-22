"""JourneyActivityRepository against a live Postgres (marker: e2e).

Needs `simulatordb` up and `uv run alembic upgrade head` applied; the DSN comes
from settings.simulatordb_url. Shared builders live in tests/conftest.py.
Run: `uv run pytest -m e2e -k activity_db`.
"""

import pytest
from sqlalchemy import delete, select

from src.config import settings
from src.external_flows.customer_journey.models.journey_activity import JourneyActivity
from src.external_flows.customer_journey.repository.journey_activity import (
    JourneyActivityRepository,
)
from src.infrastructure.db import make_engine, make_sessionmaker

pytestmark = pytest.mark.e2e


async def test_record_and_upsert_idempotent(make_arrival, make_summary):
    engine = make_engine(settings.simulatordb_url)
    sessionmaker = make_sessionmaker(engine)
    repository = JourneyActivityRepository(sessionmaker)
    arrival = make_arrival()  # random id → isolated
    try:
        await repository.record(arrival=arrival, summary=make_summary())
        await repository.record(arrival=arrival, summary=make_summary())  # same id

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(JourneyActivity).where(JourneyActivity.id == arrival.id)
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1  # upsert: one row, not two
        row = rows[0]
        assert row.journey == "guest_checkout"
        assert row.completed is True
        assert row.device == "iphone"
        assert row.visitor_city == "Seattle"  # visitor geography
        assert row.billing_country == "US"  # billing geography
        assert row.duration_ms == 5000
        assert row.details["selected_product"] == {"name": "Chest", "url": "/chest"}
    finally:
        # Clean up in finally so a failing assertion above never leaves the row
        # behind, then dispose the engine.
        async with sessionmaker() as session:
            await session.execute(
                delete(JourneyActivity).where(JourneyActivity.id == arrival.id)
            )
            await session.commit()
        await engine.dispose()


async def test_verify_ready_passes_against_migrated_db():
    engine = make_engine(settings.simulatordb_url)
    repository = JourneyActivityRepository(make_sessionmaker(engine))
    try:
        # journey_activity exists (migrations applied) → the probe succeeds.
        await repository.verify_ready()
    finally:
        await engine.dispose()
