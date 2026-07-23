"""Analytical SQL over `journey_activity`.

Aggregate queries (not ORM row hydration) — the portal reads counts and rollups,
so it talks to the schema directly with Core `text()`. The table + columns are the
contract owned by the simulator's migrations.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.schemas import Analytics, Bucket, HourCount, OutcomeCounts, Window

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

# Runs over time: one bucket per hour across the last 24h, zero-filled via a
# generate_series left join so quiet hours render as gaps (not missing columns).
# count(started_at) — not count(*) — so an empty hour is 0, not 1.
_BY_HOUR = text(
    """
    SELECT
        to_char(h.hour, 'HH24:00') AS hour,
        count(j.started_at)        AS count
    FROM generate_series(
        date_trunc('hour', now()) - interval '23 hours',
        date_trunc('hour', now()),
        interval '1 hour'
    ) AS h(hour)
    LEFT JOIN journey_activity j
        ON date_trunc('hour', j.started_at) = h.hour
    GROUP BY h.hour
    ORDER BY h.hour
    """
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
    hours = (await conn.execute(_BY_HOUR)).mappings().all()
    return Analytics(
        window=Window(**window),
        outcome=OutcomeCounts(**outcome),
        by_journey=[Bucket(**r) for r in journeys],
        by_device=[Bucket(**r) for r in devices],
        by_hour=[HourCount(**r) for r in hours],
    )
