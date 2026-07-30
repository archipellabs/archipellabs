"""The configuration service against a live Postgres (marker: e2e).

Needs `simulatordb` up and `uv run alembic upgrade head` applied. The unit suite
covers the resolution rules with an in-memory table; this covers the parts only a
real database can answer — that the JSONB round trip preserves a dict, that the
upsert is idempotent, and that clearing genuinely falls back to the layer below.

Run: `uv run pytest -m e2e -k configuration_db`.
"""

import pytest

from src.config import settings
from src.infrastructure.db import make_engine, make_sessionmaker
from src.services.configuration.service import Configuration
from src.services.configuration.service import configuration as process_configuration
from src.technical_flows.configuration.actions import apply
from src.technical_flows.contracts import ConfigChange

pytestmark = pytest.mark.e2e

KEY = "market_mix"
"""A dict-valued tunable on purpose: a str or int would survive a sloppy round
trip through JSONB, and this is where that would show."""


@pytest.fixture
async def configuration():
    engine = make_engine(settings.simulatordb_url)
    service = Configuration()
    service.use(make_sessionmaker(engine))
    try:
        yield service
    finally:
        # Never leave an override behind: the running simulator reads this table.
        await service.clear(KEY)
        await engine.dispose()


async def test_an_override_round_trips_through_jsonb(configuration):
    await configuration.set(KEY, {"US": 0.5, "CA": 0.5})

    assert configuration.get(KEY) == {"US": 0.5, "CA": 0.5}


async def test_setting_twice_updates_rather_than_conflicts(configuration):
    await configuration.set(KEY, {"US": 1.0})
    await configuration.set(KEY, {"CA": 1.0})

    # Second write wins; a failed upsert would raise or leave the first value.
    assert configuration.get(KEY) == {"CA": 1.0}


async def test_describe_reads_the_stored_value_back_as_a_database_source(
    configuration,
):
    await configuration.set(KEY, {"US": 0.9, "CA": 0.1})

    described = await configuration.describe()

    assert described[KEY]["source"] == "database"
    assert described[KEY]["value"] == {"US": 0.9, "CA": 0.1}
    assert described[KEY]["static"] == settings.market_mix


async def test_clearing_falls_back_to_the_layer_below(configuration):
    await configuration.set(KEY, {"US": 1.0})

    await configuration.clear(KEY)

    assert configuration.get(KEY) == settings.market_mix


async def test_the_apply_action_stores_a_value_change_in_the_database():
    """The control plane's value branch, against the real store.

    The component test proves the queue reaches the handler; this proves the
    handler's write lands where a restart will find it.
    """
    engine = make_engine(settings.simulatordb_url)
    process_configuration.use(make_sessionmaker(engine))
    try:
        result = await apply(None, ConfigChange(key=KEY, value={"US": 0.6, "CA": 0.4}))

        assert result["kind"] == "value"
        assert result["source"] == "database"
        assert process_configuration.get(KEY) == {"US": 0.6, "CA": 0.4}
    finally:
        await process_configuration.clear(KEY)
        await engine.dispose()


async def test_a_second_process_sees_a_stored_override(configuration):
    """What the portal→simulator path depends on: the override is in the database,
    not in the writer's memory, so a different process resolves the same value."""
    await configuration.set(KEY, {"US": 0.25, "CA": 0.75})

    engine = make_engine(settings.simulatordb_url)
    reader = Configuration()
    reader.use(make_sessionmaker(engine))
    try:
        await reader.refresh()
        assert reader.get(KEY) == {"US": 0.25, "CA": 0.75}
    finally:
        await engine.dispose()
