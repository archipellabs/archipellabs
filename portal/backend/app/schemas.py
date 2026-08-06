"""Response models — the portal API's public shape (independent of the DB schema)."""

from pydantic import BaseModel, Field


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


class Ask(BaseModel):
    """A question put to one analyst, with the configuration to answer it under.

    `model` and `effort` travel with the request rather than being read from the
    agent's own environment. They used to be process-level, which meant comparing
    two models from a browser was impossible: you edited a `.env` and restarted
    an employee.
    """

    agent: str = Field(description="Which employee to ask.")
    question: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="gpt-5.6-luna")
    effort: str = Field(default="low")


class Asked(BaseModel):
    """The receipt: what to open a stream on."""

    reference: str = Field(description="Mint per request; every event echoes it.")
    agent: str


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class Session(BaseModel):
    """Whether this browser may use the pages that are not read-only.

    `configured` is separate from `signed_in` so the page can tell a visitor who
    needs to sign in from an operator who has not set a password — one is a
    prompt, the other is a deployment that closed its own doors.
    """

    signed_in: bool
    configured: bool
    required: bool
    """Whether this deployment asks at all. False means the two pages are open,
    and the browser should render them rather than a form nothing would accept."""


class SettingChange(BaseModel):
    """One knob, and what to set it to.

    Mirrors the simulator's own `ConfigChange`, including its sentinel: **null
    means reset** — drop the override and fall back to the environment or the
    shipped default. Every tunable rejects null as a real value, so the meaning
    is unambiguous.
    """

    key: str = Field(min_length=1, max_length=64)
    value: object | None = None
