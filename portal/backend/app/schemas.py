"""Response models — the portal API's public shape (independent of the DB schema)."""

from pydantic import BaseModel


class OutcomeCounts(BaseModel):
    """Every run bucketed into exactly one outcome (mutually exclusive, sums to total)."""

    completed: int
    abandoned: int
    errored: int
    other: int


class Bucket(BaseModel):
    """A count for one category (journey name, device, …)."""

    key: str
    count: int


class HourCount(BaseModel):
    """Runs in one hourly bucket over the last 24h (zero-filled, 24 buckets)."""

    hour: str
    count: int


class Window(BaseModel):
    """Counts over recent time windows, relative to now."""

    last_24h: int
    last_1h: int


class Analytics(BaseModel):
    window: Window
    outcome: OutcomeCounts
    by_journey: list[Bucket]
    by_device: list[Bucket]
    by_hour: list[HourCount]
