"""The configuration service, tested against an in-memory overrides table.

No database needed: what matters here is the resolution order (database →
environment → shipped default), the fact that `get` never does I/O, and that
detaching leaves a process reading the static layer. The session count the fake
keeps is how the caching claims become assertions.
"""

import asyncio

import pytest

from src.config import Settings, settings
from src.services.configuration import service as service_module
from src.services.configuration.models import SimulatorSetting
from src.services.configuration.service import Configuration, validate
from tests.conftest import FakeSettingsDb


def _configured(ttl: float = 60.0, **overrides) -> tuple[Configuration, FakeSettingsDb]:
    db = FakeSettingsDb(**overrides)
    configuration = Configuration(ttl_seconds=ttl)
    configuration.use(db)  # type: ignore[arg-type]
    return configuration, db


async def test_a_non_tunable_key_never_opens_a_session():
    configuration, db = _configured()

    assert configuration.get("redis_url") == settings.redis_url
    assert db.opened == 0


async def test_a_tunable_falls_back_to_the_static_layer():
    configuration, _ = _configured()
    await configuration.refresh()

    assert (
        configuration.get("base_arrivals_per_minute")
        == settings.base_arrivals_per_minute
    )


async def test_a_stored_override_wins_over_the_static_layer():
    configuration, _ = _configured(base_arrivals_per_minute=9.0)
    await configuration.refresh()

    assert configuration.get("base_arrivals_per_minute") == 9.0


async def test_reads_are_served_from_the_snapshot_without_querying():
    configuration, db = _configured(base_arrivals_per_minute=9.0)
    await configuration.refresh()

    for _ in range(50):
        assert configuration.get("base_arrivals_per_minute") == 9.0

    assert db.opened == 1  # the one explicit refresh, and nothing since


async def test_a_stale_read_answers_at_once_and_reloads_behind_it():
    configuration, db = _configured(ttl=0.0, base_arrivals_per_minute=9.0)
    await configuration.refresh()

    db.rows = [SimulatorSetting(key="base_arrivals_per_minute", value=42.0)]
    # The row moved, but a stale read still answers instantly from the snapshot —
    # `get` is synchronous and sits on the arrivals hot path, so it never waits.
    assert configuration.get("base_arrivals_per_minute") == 9.0

    # The reload it scheduled brings the new value in behind it.
    await asyncio.sleep(0.05)
    assert configuration.get("base_arrivals_per_minute") == 42.0


async def test_without_a_database_everything_answers_from_the_static_layer():
    configuration = Configuration()

    assert configuration.get("fast") == settings.fast
    assert configuration.get("redis_url") == settings.redis_url


async def test_detaching_drops_the_overrides_with_the_database():
    configuration, _ = _configured(base_arrivals_per_minute=9.0)
    await configuration.refresh()
    assert configuration.get("base_arrivals_per_minute") == 9.0

    configuration.use(None)

    assert (
        configuration.get("base_arrivals_per_minute")
        == settings.base_arrivals_per_minute
    )


async def test_a_stored_value_that_no_longer_validates_falls_back(caplog):
    # A renamed tunable or a hand-edited row must not take the tick down with it.
    configuration, _ = _configured(base_arrivals_per_minute={"nonsense": True})
    await configuration.refresh()

    assert (
        configuration.get("base_arrivals_per_minute")
        == settings.base_arrivals_per_minute
    )
    assert "ignoring stored setting base_arrivals_per_minute" in caplog.text


async def test_an_unknown_key_is_rejected_rather_than_defaulted():
    configuration, _ = _configured()

    with pytest.raises(KeyError):
        configuration.get("nonexistent_key")


async def test_writing_without_a_database_says_so():
    configuration = Configuration()

    with pytest.raises(RuntimeError, match="no database"):
        await configuration.set("fast", True)


async def test_describe_reports_a_database_override_as_such():
    configuration, _ = _configured(fast=True)

    described = await configuration.describe()

    assert described["fast"] == {
        "value": True,
        "source": "database",
        # What clearing the override would restore, and what ships in code.
        "static": settings.fast,
        "default": Settings.model_fields["fast"].default,
    }


async def test_describe_reports_an_untouched_key_as_the_shipped_default():
    configuration, _ = _configured()

    described = await configuration.describe()

    assert described["market_mix"]["source"] == "default"
    assert (
        described["market_mix"]["value"] == Settings.model_fields["market_mix"].default
    )


async def test_describe_tells_an_environment_value_apart_from_a_default(monkeypatch):
    # The distinction a reset button depends on: with the environment setting the
    # key, clearing an override lands on the deployment's value, not on 1000.
    monkeypatch.setenv("MAX_ARRIVALS_PER_TICK", "250")
    monkeypatch.setattr(service_module, "settings", Settings())
    configuration, _ = _configured()

    described = await configuration.describe()

    assert described["max_arrivals_per_tick"] == {
        "value": 250,
        "source": "environment",
        "static": 250,
        "default": Settings.model_fields["max_arrivals_per_tick"].default,
    }


async def test_a_database_override_outranks_the_environment(monkeypatch):
    monkeypatch.setenv("MAX_ARRIVALS_PER_TICK", "250")
    monkeypatch.setattr(service_module, "settings", Settings())
    configuration, _ = _configured(max_arrivals_per_tick=7)

    described = await configuration.describe()

    assert configuration.get("max_arrivals_per_tick") == 7
    assert described["max_arrivals_per_tick"]["source"] == "database"
    assert described["max_arrivals_per_tick"]["static"] == 250  # what a clear restores


def test_validate_coerces_the_wire_shape():
    # Values arrive as JSON from an HTTP call, so "5" has to become 5.
    assert validate("max_arrivals_per_tick", "5") == 5


def test_validate_rejects_a_bad_shape():
    with pytest.raises(ValueError):
        validate("market_mix", {"US": "lots"})


def test_validate_refuses_a_key_that_is_not_tunable():
    with pytest.raises(KeyError):
        validate("redis_url", "redis://elsewhere")
