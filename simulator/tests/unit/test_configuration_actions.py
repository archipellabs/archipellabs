"""The configuration control plane: routing, the flow switches, and refusals.

The handlers are returned unchanged by `@service.action`, so they are callable
directly with a fake ctx. The value path writes to the database and is covered
against a real Postgres in `tests/e2e/test_configuration_db.py`; what is hermetic
here is everything that decides *where* a change goes and what it refuses.
"""

import pytest

from src.services.configuration.service import TUNABLES
from src.technical_flows.configuration.actions import FLOW_SWITCHES, apply, describe
from src.technical_flows.contracts import ConfigChange


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


async def test_pausing_a_flow_flips_its_runtime_switch():
    ctx = FakeCtx()

    result = await apply(ctx, ConfigChange(key="customer-arrivals", value=False))

    assert ctx.flips == [("customer-arrivals", False)]
    assert result == {"key": "customer-arrivals", "kind": "flow", "running": False}


async def test_resuming_a_flow_flips_it_back():
    ctx = FakeCtx("customer-arrivals")

    await apply(ctx, ConfigChange(key="customer-arrivals", value=True))

    assert ctx.is_enabled("customer-arrivals")


async def test_resetting_a_flow_means_running():
    # Absent from the registry means enabled, so "reset" and "resume" are the
    # same operation — the sentinel has to mean that for both kinds of key.
    ctx = FakeCtx("catalog-doctor")

    result = await apply(ctx, ConfigChange(key="catalog-doctor"))

    assert result["running"] is True
    assert ctx.is_enabled("catalog-doctor")


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


async def test_describe_reports_both_kinds_with_their_state():
    ctx = FakeCtx("stock-refill")

    described = await describe(ctx, None)

    assert set(described["values"]) == set(TUNABLES)
    assert described["values"]["fast"]["source"] == "default"
    assert described["flows"]["stock-refill"]["running"] is False
    assert described["flows"]["customer-journey"]["running"] is True


def test_every_switch_name_is_one_the_runtime_actually_registers():
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

    assert set(FLOW_SWITCHES) <= known
