"""journey_activity

Revision ID: 0001
Revises:
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journey_activity",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("journey", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("abandoned", sa.Boolean(), nullable=False),
        sa.Column("abandoned_from", sa.String(), nullable=True),
        sa.Column("order_reference", sa.String(), nullable=True),
        sa.Column("intent_type", sa.String(), nullable=True),
        sa.Column("device", sa.String(), nullable=True),
        sa.Column("visitor_city", sa.String(), nullable=True),
        sa.Column("billing_country", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "details",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_journey_activity_started_at", "journey_activity", ["started_at"]
    )
    op.create_index("ix_journey_activity_journey", "journey_activity", ["journey"])
    op.create_index("ix_journey_activity_completed", "journey_activity", ["completed"])
    op.create_index("ix_journey_activity_device", "journey_activity", ["device"])


def downgrade() -> None:
    op.drop_table("journey_activity")
