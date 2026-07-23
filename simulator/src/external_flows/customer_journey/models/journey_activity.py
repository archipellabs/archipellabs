"""The `journey_activity` entity — one row per recorded customer-journey run.

Structured, chartable facts about what each journey did (not the operational log
trace — that stays in FlowTrace). Read by the coming charts app.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db import Base


class JourneyActivity(Base):
    """One recorded customer-journey run — the unit charts are built from.

    `id` is the arrival id (`a_…`), reused as the run id, so a replay of the same
    arrival is an idempotent insert rather than a duplicate row.
    """

    __tablename__ = "journey_activity"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    journey: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # success | error
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    abandoned: Mapped[bool] = mapped_column(Boolean, nullable=False)
    abandoned_from: Mapped[str | None] = mapped_column(String)
    order_reference: Mapped[str | None] = mapped_column(String)
    # buy_products | browse_discover
    intent_type: Mapped[str | None] = mapped_column(String)
    device: Mapped[str | None] = mapped_column(String)
    # Visitor geography (where they browse from) — from the visitor envelope.
    visitor_city: Mapped[str | None] = mapped_column(String)
    # Billing geography (the checkout country) — from the customer profile. Kept
    # separate from visitor_city: the two can legitimately differ for one run.
    billing_country: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(String)
    # Small structured extras (selected_product, cart_count, final_url) — NOT the
    # raw event trace, which belongs to the logs side. `default=dict` fills it on
    # ORM inserts; `server_default` mirrors the migration so the model and DB agree.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_journey_activity_started_at", "started_at"),
        Index("ix_journey_activity_journey", "journey"),
        Index("ix_journey_activity_completed", "completed"),
        Index("ix_journey_activity_device", "device"),
    )
