"""Activity repository unit tests — no real database.

Covered here with the DB mocked out (shared builders live in tests/conftest.py):
  - `journey_activity_values`: the summary → column mapping, pure (no DB).
  - `JourneyActivityRepository.record`: persistence wiring against a fake
    sessionmaker (executes + commits, best-effort, logs a DB outage once).
  - `JourneyActivityRepository.verify_ready`: the fail-fast startup probe.
The same repository against a live Postgres lives in tests/integration.
"""

import logging
from typing import Any

import pytest

from src.external_flows.contracts import CustomerIntentType
from src.external_flows.customer_journey.repository.journey_activity import (
    JourneyActivityRepository,
    journey_activity_values,
)


def test_completed_guest_checkout_maps_to_columns(make_arrival, make_summary):
    arrival = make_arrival()
    values = journey_activity_values(arrival, make_summary())

    assert values["id"] == arrival.id  # the run id is the arrival id (idempotent)
    assert values["journey"] == "guest_checkout"
    assert values["status"] == "success"
    assert values["completed"] is True
    assert values["abandoned"] is False
    assert values["order_reference"] == "ORDER123"
    assert values["intent_type"] == "buy_products"
    assert values["device"] == "iphone"
    assert values["visitor_city"] == "Seattle"  # visitor geography
    assert values["billing_country"] == "US"  # checkout/billing geography
    assert values["duration_ms"] == 5000
    assert values["error_type"] is None
    assert values["details"]["selected_product"] == {"name": "Chest", "url": "/chest"}
    assert values["details"]["cart_count"] == 1


def test_abandoned_journey(make_arrival, make_summary):
    values = journey_activity_values(
        make_arrival(),
        make_summary(
            journey="add_to_cart_abandon",
            completed=False,
            abandoned=True,
            abandoned_from="continue_shopping",
            order_reference=None,
        ),
    )
    assert values["status"] == "success"
    assert values["completed"] is False
    assert values["abandoned"] is True
    assert values["abandoned_from"] == "continue_shopping"
    assert values["order_reference"] is None


def test_errored_run(make_arrival, make_summary):
    values = journey_activity_values(
        make_arrival(),
        make_summary(
            success=False,
            completed=False,
            error={"type": "TimeoutError", "message": "boom"},
        ),
    )
    assert values["status"] == "error"
    assert values["error_type"] == "TimeoutError"
    assert values["error_message"] == "boom"


def test_missing_visitor_separates_visitor_from_billing(make_arrival, make_summary):
    arrival = make_arrival(
        country="CA",
        intent=CustomerIntentType.BROWSE_DISCOVER,
        with_visitor=False,
    )
    values = journey_activity_values(arrival, make_summary())

    # No envelope → no visitor geography, but the billing country still stands.
    assert values["device"] is None
    assert values["visitor_city"] is None
    assert values["billing_country"] == "CA"
    assert values["intent_type"] == "browse_discover"


# --- record() / verify_ready() with a mocked DB --------------------------------
# A fake sessionmaker stands in for async_sessionmaker so record()/verify_ready()
# can be unit tested without Postgres.


class _FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.executed: list[Any] = []
        self.committed = False
        self.fail = fail

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> None:
        if self.fail:
            raise RuntimeError("db down")
        self.executed.append(stmt)

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionmaker:
    """Calling it returns the session (itself an async context manager)."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSession:
        return self._session


async def test_record_executes_and_commits(make_arrival, make_summary):
    session = _FakeSession()
    repository = JourneyActivityRepository(_FakeSessionmaker(session))

    await repository.record(arrival=make_arrival(), summary=make_summary())

    assert len(session.executed) == 1  # one upsert statement
    assert session.committed is True


async def test_record_swallows_db_errors(make_arrival, make_summary):
    session = _FakeSession(fail=True)
    repository = JourneyActivityRepository(_FakeSessionmaker(session))

    # Best-effort: a DB failure must not propagate or fail the journey handler.
    await repository.record(arrival=make_arrival(), summary=make_summary())

    assert session.committed is False


async def test_record_logs_a_db_outage_once_then_recovers(
    make_arrival, make_summary, caplog
):
    session = _FakeSession(fail=True)
    repository = JourneyActivityRepository(_FakeSessionmaker(session))

    with caplog.at_level(logging.INFO, logger="simulator.activity"):
        await repository.record(arrival=make_arrival(), summary=make_summary())  # fail
        await repository.record(arrival=make_arrival(), summary=make_summary())  # fail
        session.fail = False  # DB comes back
        await repository.record(arrival=make_arrival(), summary=make_summary())  # ok

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    messages = [r.getMessage() for r in caplog.records]
    assert len(errors) == 1  # a whole outage logs one traceback, not one per arrival
    assert any("recovered" in m for m in messages)
    assert session.committed is True


async def test_verify_ready_passes_when_db_reachable():
    session = _FakeSession()
    repository = JourneyActivityRepository(_FakeSessionmaker(session))

    await repository.verify_ready()  # must not raise

    assert len(session.executed) == 1  # it probed the table


async def test_verify_ready_fails_fast_when_db_unavailable():
    session = _FakeSession(fail=True)
    repository = JourneyActivityRepository(_FakeSessionmaker(session))

    # Unlike record(), verify_ready() re-raises so startup aborts loudly instead of
    # every arrival swallowing the error.
    with pytest.raises(RuntimeError):
        await repository.verify_ready()
