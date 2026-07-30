"""The configuration control plane: routing, the flow switches, and refusals.

The handlers are returned unchanged by `@service.action`, so they are callable
directly with a fake ctx. The value path writes to the database and is covered
against a real Postgres in `tests/e2e/test_configuration_db.py`; what is hermetic
here is everything that decides *where* a change goes and what it refuses.
"""

import pytest

from src.services.configuration import service as service_module
from src.services.configuration.service import TUNABLES
from src.technical_flows.configuration.actions import (
    FLOW_ENABLE_FLAGS,
    apply,
    describe,
    replay_flow_flags,
)
from src.technical_flows.contracts import ConfigChange
from tests.conftest import use_overrides


@pytest.fixture(autouse=True)
def mounted_services(monkeypatch):
    """Keep unit behavior independent of the developer's local enable flags."""
    for flag in (
        "journey_enabled",
        "arrivals_enabled",
        "catalog_enabled",
        "stock_enabled",
        "payments_enabled",
    ):
        monkeypatch.setattr(service_module.settings, flag, True)


@pytest.fixture(autouse=True)
async def settings_db():
    """A flow flag is stored, so every test needs somewhere to store it."""
    return await use_overrides()


class FakeCtx:
    """A context whose only real behaviour is the switch registry."""

    def __init__(self, *paused: str) -> None:
        self.paused = set(paused)
        self.flips: list[tuple[str, bool]] = []

    def is_enabled(self, name: str) -> bool:
        return name not in self.paused

    async def set_enabled(self, name: str, enabled: bool) -> None:
        self.flips.append((name, enabled))
        if enabled:
            self.paused.discard(name)
        else:
            self.paused.add(name)


async def test_pausing_a_flow_records_it_and_projects_it(settings_db):
    """Both halves matter. The database keeps the decision; the registry is how
    workers find out. Either alone is a pause that does nothing, or one that
    evaporates with Redis."""
    ctx = FakeCtx()

    result = await apply(ctx, ConfigChange(key="customer-journey", value=False))

    assert result == {
        "key": "customer-journey",
        "kind": "flow",
        "mounted": True,
        "running": False,
    }
    assert ctx.flips == [("customer-journey", False)]  # projected onto Redis
    assert {r.key: r.value for r in settings_db.rows} == {
        "flow:customer-journey": False
    }


async def test_a_pause_outlives_a_wiped_switch_registry():
    """The whole reason the flag is in the database.

    Redis is transport and goes away with the stack, so a new process starts on
    an empty registry — which means "everything running" — while the database
    still holds what someone decided.
    """
    await apply(FakeCtx(), ConfigChange(key="catalog-doctor", value=False))

    restarted = FakeCtx()  # fresh Redis: nothing paused
    await replay_flow_flags(restarted)

    assert restarted.is_enabled("catalog-doctor") is False
    assert restarted.is_enabled("customer-journey") is True


async def test_resuming_a_flow_flips_it_back():
    ctx = FakeCtx()
    await apply(ctx, ConfigChange(key="customer-journey", value=False))

    await apply(ctx, ConfigChange(key="customer-journey", value=True))

    assert ctx.is_enabled("customer-journey")


async def test_resetting_a_flow_drops_the_row_and_means_running(settings_db):
    # Absent means running, so "reset" and "resume" land in the same place — the
    # sentinel has to mean that for both kinds of key.
    ctx = FakeCtx()
    await apply(ctx, ConfigChange(key="stock-refill", value=False))

    result = await apply(ctx, ConfigChange(key="stock-refill"))

    assert result["running"] is True
    assert ctx.is_enabled("stock-refill")
    assert settings_db.rows == []  # reset removes the row, it does not store True


async def test_a_flow_refuses_a_value_that_is_not_a_switch_position():
    ctx = FakeCtx()

    with pytest.raises(ValueError, match="true or false"):
        await apply(ctx, ConfigChange(key="customer-journey", value=3))

    assert ctx.flips == []


async def test_an_unknown_key_is_refused_and_says_what_is_available():
    # One letter off is the realistic mistake; accepting it and reporting success
    # is worse than having no typo protection, because the caller stops looking.
    ctx = FakeCtx()

    with pytest.raises(KeyError) as excinfo:
        await apply(ctx, ConfigChange(key="base_arrival_per_minute", value=9))

    message = str(excinfo.value)
    assert "base_arrivals_per_minute" in message  # the tunable it nearly named
    assert "customer-journey" in message  # and the flows, so both are discoverable


async def test_a_wiring_flag_is_not_offered_as_a_runtime_knob():
    """`journey_enabled` gates `include()`, which runs once at boot.

    Accepting it here would store a value, report it applied, and change nothing —
    the exact silent no-op the switch registry exists to avoid.
    """
    ctx = FakeCtx()

    with pytest.raises(KeyError):
        await apply(ctx, ConfigChange(key="journey_enabled", value=False))


async def test_an_unmounted_flow_is_reported_and_cannot_be_switched(monkeypatch):
    monkeypatch.setattr(service_module.settings, "journey_enabled", False)
    ctx = FakeCtx()

    described = await describe(ctx, None)

    assert described["flows"]["customer-journey"]["mounted"] is False
    assert described["flows"]["customer-journey"]["running"] is False
    with pytest.raises(ValueError, match="not mounted"):
        await apply(ctx, ConfigChange(key="customer-journey", value=True))
    assert ctx.flips == []


async def test_describe_reports_both_kinds_with_their_state():
    ctx = FakeCtx()
    await apply(ctx, ConfigChange(key="stock-refill", value=False))

    described = await describe(ctx, None)

    assert set(described["values"]) == set(TUNABLES)
    assert described["values"]["fast"]["source"] == "default"
    assert described["flows"]["stock-refill"]["mounted"] is True
    assert described["flows"]["stock-refill"]["running"] is False
    assert described["flows"]["customer-journey"]["running"] is True


def test_every_mounted_switch_name_is_one_the_runtime_actually_registers():
    """The names here must match the topology, or a pause is a silent no-op.

    A switch name that nothing checks is accepted by Redis, reported as applied,
    and never consulted — so this pins them against the services themselves.
    """
    from src.app import build_app

    app = build_app()
    services = [inc.service for inc in app._services]
    # Service names are master switches; producer ids are the finer level. Both
    # are what `is_enabled` is called with, so both are legal switch names.
    known = {service.name for service in services}
    known |= {producer.id for service in services for producer in service._every}

    mounted = {
        name
        for name, flags in FLOW_ENABLE_FLAGS.items()
        if all(getattr(service_module.settings, flag) for flag in flags)
    }
    assert mounted <= known
