"""Shared test scaffolding: the configuration harness and the arrival builders.

Two things live here. First, an in-memory stand-in for the overrides table plus
the autouse fixture that detaches the process configuration between tests — the
configuration is process-wide, so without it one test's override silently becomes
every later test's default.

Second, factory fixtures (they yield a `_make(...)` callable, not a fixed object)
so each test builds only the fields it cares about without re-declaring the
CustomerArrivalEvent / CustomerProfile / summary shape in every module.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from src.external_flows.contracts import (
    CustomerArrivalEvent,
    CustomerIntent,
    CustomerIntentType,
    CustomerProfile,
    VisitorEnvelope,
)
from src.services.configuration.models import SimulatorSetting
from src.services.configuration.service import configuration


class _FakeResult:
    def __init__(self, rows: list[SimulatorSetting]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[SimulatorSetting]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[SimulatorSetting]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, statement: object) -> _FakeResult:
        return _FakeResult(self._rows)


class FakeSettingsDb:
    """The overrides table, in memory, shaped like a sessionmaker.

    Counts the sessions it opens, which is how the caching tests observe round
    trips without a database to instrument.
    """

    def __init__(self, **overrides: Any) -> None:
        self.rows = [SimulatorSetting(key=k, value=v) for k, v in overrides.items()]
        self.opened = 0

    def __call__(self) -> _FakeSession:
        self.opened += 1
        return _FakeSession(self.rows)


async def use_overrides(**values: Any) -> FakeSettingsDb:
    """Point the process configuration at an in-memory overrides table, loaded.

    The real resolution path, minus the database: a test that wants a knob at some
    value stores it the way the portal would, rather than stubbing the getter.
    """
    db = FakeSettingsDb(**values)
    configuration.use(db)  # type: ignore[arg-type]
    await configuration.refresh()
    return db


@pytest.fixture(autouse=True)
def static_configuration():
    """Every test starts detached: static layer only, no overrides leaked in.

    The configuration is process-wide, so without this a test that stores an
    override would change the answers every later test gets.
    """
    configuration.use(None)
    yield
    configuration.use(None)


@pytest.fixture
def make_profile() -> Callable[..., CustomerProfile]:
    def _make(country: str = "US") -> CustomerProfile:
        return CustomerProfile(
            firstname="A",
            lastname="B",
            email="a.b@example.com",
            address1="1 St",
            city="Town",
            postcode="12345",
            phone="",
            country=country,
        )

    return _make


@pytest.fixture
def make_arrival(
    make_profile: Callable[..., CustomerProfile],
) -> Callable[..., CustomerArrivalEvent]:
    def _make(
        *,
        country: str = "US",
        intent: CustomerIntentType = CustomerIntentType.BUY_PRODUCTS,
        with_visitor: bool = True,
    ) -> CustomerArrivalEvent:
        visitor = (
            VisitorEnvelope(
                device="iphone",
                ip="128.95.104.7",
                city="Seattle",
                timezone="America/Los_Angeles",
            )
            if with_visitor
            else None
        )
        return CustomerArrivalEvent.create(
            intent=CustomerIntent(
                type=intent, customer=make_profile(country), products=[]
            ),
            visitor=visitor,
        )

    return _make


@pytest.fixture
def make_summary() -> Callable[..., dict[str, Any]]:
    def _make(**over: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "flow_id": "ignored",
            "journey": "guest_checkout",
            "success": True,
            "completed": True,
            "abandoned": False,
            "abandoned_from": None,
            "error": None,
            "order_reference": "ORDER123",
            "selected_product": {"name": "Chest", "url": "/chest"},
            "cart_count": 1,
            "final_url": "/order-confirmation",
            "started_at": datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
            "finished_at": datetime(2026, 7, 21, 12, 0, 5, tzinfo=UTC),
        }
        base.update(over)
        return base

    return _make
