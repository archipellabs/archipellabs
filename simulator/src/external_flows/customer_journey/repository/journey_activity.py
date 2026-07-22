"""Persist customer-journey runs — the flow's activity repository.

The flow-specific persistence calls live here (generic engine/session plumbing is
in src/infrastructure/db.py). Built on a shared sessionmaker + this flow's own
entity. Best-effort: a DB hiccup is logged (once per outage) and swallowed, never raised,
so it can neither fail the journey nor trigger a redelivery.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.external_flows.contracts import CustomerArrivalEvent
from src.external_flows.customer_journey.models.journey_activity import JourneyActivity

log = logging.getLogger("simulator.activity")


def _duration_ms(
    started_at: datetime | None, finished_at: datetime | None
) -> int | None:
    if started_at is None or finished_at is None:
        return None
    return int((finished_at - started_at).total_seconds() * 1000)


def journey_activity_values(
    arrival: CustomerArrivalEvent, summary: dict[str, Any]
) -> dict[str, Any]:
    """Map a journey summary + its arrival to `journey_activity` column values.

    Pure (no DB) so it is unit-testable. `created_at` is left to the DB default.
    """
    error = summary.get("error")
    visitor = arrival.visitor
    return {
        "id": arrival.id,  # == summary["flow_id"], the correlation/run id
        "journey": summary["journey"],
        "status": "success" if summary.get("success") else "error",
        "completed": bool(summary.get("completed")),
        "abandoned": bool(summary.get("abandoned")),
        "abandoned_from": summary.get("abandoned_from"),
        "order_reference": summary.get("order_reference"),
        "intent_type": arrival.intent.type.value,
        "device": visitor.device if visitor else None,
        # Two distinct geographies, deliberately kept apart: where the visitor
        # browses from (envelope) vs the country they check out under (billing).
        "visitor_city": visitor.city if visitor else None,
        "billing_country": arrival.intent.customer.country,
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at"),
        "duration_ms": _duration_ms(
            summary.get("started_at"), summary.get("finished_at")
        ),
        "error_type": error["type"] if error else None,
        "error_message": error["message"] if error else None,
        "details": {
            "selected_product": summary.get("selected_product"),
            "cart_count": summary.get("cart_count"),
            "final_url": summary.get("final_url"),
        },
    }


class JourneyActivityRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        # True once a write has failed, until one succeeds again — lets record() log
        # a DB outage once instead of a traceback per arrival.
        self._degraded = False

    async def verify_ready(self) -> None:
        """Fail fast at startup if the activity DB is unreachable or unmigrated.

        Called once from the pool lifespan (like a health check in a FastAPI
        lifespan). Probes the journey_activity table, so a wrong DSN or a forgotten
        `alembic upgrade head` surfaces immediately as a startup error — instead of
        being swallowed by `record` on every single arrival.
        """
        try:
            async with self._sessionmaker() as session:
                await session.execute(select(JourneyActivity.id).limit(1))
        except Exception as exc:
            raise RuntimeError(
                "activity database is not reachable or not migrated — bring "
                "`simulatordb` up and run `alembic upgrade head`"
            ) from exc

    async def record(
        self, *, arrival: CustomerArrivalEvent, summary: dict[str, Any]
    ) -> None:
        """Upsert one journey run (idempotent on the arrival id). Best-effort."""
        try:
            values = journey_activity_values(arrival, summary)
            stmt = (
                pg_insert(JourneyActivity)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            async with self._sessionmaker() as session:
                await session.execute(stmt)
                await session.commit()
        except Exception:
            # Best-effort: never fail the journey. Log the FIRST failure loudly
            # (with traceback), then stay quiet until a write succeeds again, so a DB
            # outage can't spam one traceback per arrival.
            if not self._degraded:
                self._degraded = True
                log.exception(
                    "activity recording failed for %s; suppressing further errors "
                    "until it recovers",
                    arrival.id,
                )
            return
        if self._degraded:
            self._degraded = False
            log.info("activity recording recovered")
