"""Analytical SQL over `journey_activity`.

Aggregate queries (not ORM row hydration) — the portal reads counts and rollups,
so it talks to the schema directly with Core `text()`. The table + columns are the
contract owned by the simulator's migrations.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.schemas import Analytics, Bucket, DayCount, OutcomeCounts, Window

# One mutually-exclusive bucket per run (priority: errored > completed > abandoned),
# so the four counts partition every row — exactly what a proportion bar needs.
_OUTCOME = text(
    """
    SELECT
        count(*) FILTER (WHERE status = 'error')                                      AS errored,
        count(*) FILTER (WHERE status <> 'error' AND completed)                       AS completed,
        count(*) FILTER (WHERE status <> 'error' AND NOT completed AND abandoned)     AS abandoned,
        count(*) FILTER (WHERE status <> 'error' AND NOT completed AND NOT abandoned) AS other
    FROM journey_activity
    """
)

_BY_JOURNEY = text(
    "SELECT journey AS key, count(*) AS count "
    "FROM journey_activity GROUP BY journey ORDER BY count DESC, journey"
)

_BY_DEVICE = text(
    "SELECT coalesce(device, 'unknown') AS key, count(*) AS count "
    "FROM journey_activity GROUP BY device ORDER BY count DESC, key"
)

_BY_DAY = text(
    "SELECT to_char(date_trunc('day', started_at), 'YYYY-MM-DD') AS day, "
    "count(*) AS count FROM journey_activity GROUP BY 1 ORDER BY 1"
)

_WINDOW = text(
    """
    SELECT
        count(*) FILTER (WHERE started_at >= now() - interval '24 hours') AS last_24h,
        count(*) FILTER (WHERE started_at >= now() - interval '1 hour')   AS last_1h
    FROM journey_activity
    """
)


async def get_analytics(conn: AsyncConnection) -> Analytics:
    window = (await conn.execute(_WINDOW)).mappings().one()
    outcome = (await conn.execute(_OUTCOME)).mappings().one()
    journeys = (await conn.execute(_BY_JOURNEY)).mappings().all()
    devices = (await conn.execute(_BY_DEVICE)).mappings().all()
    days = (await conn.execute(_BY_DAY)).mappings().all()
    return Analytics(
        window=Window(**window),
        outcome=OutcomeCounts(**outcome),
        by_journey=[Bucket(**r) for r in journeys],
        by_device=[Bucket(**r) for r in devices],
        by_day=[DayCount(**r) for r in days],
    )
