"""Shared test builders — one home for the activity-test fixtures.

Factory fixtures (they yield a `_make(...)` callable, not a fixed object) so each
test builds only the fields it cares about without re-declaring the
CustomerArrivalEvent / CustomerProfile / summary shape in every module. Used by
both the unit (`tests/unit/test_activity.py`) and integration
(`tests/integration/test_activity_db.py`) suites.
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
