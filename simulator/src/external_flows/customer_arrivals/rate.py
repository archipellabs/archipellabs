"""Customer arrival-rate model used by the arrivals flow."""

import math
import random
from datetime import datetime
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

DAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Universal shape curves — the weekly/daily rhythm every shop roughly follows.
# These are constants, not config: no run overrides them. Only per-shop knobs
# (base rate, timezone, noise) live in RateConfig. Further multipliers
# (seasonal campaigns, holidays) plug into the same multiplicative model later.
DAY_OF_WEEK_MULTIPLIER: dict[str, float] = {
    "monday": 0.8,
    "tuesday": 0.9,
    "wednesday": 1.0,
    "thursday": 1.1,
    "friday": 1.4,
    "saturday": 2.2,
    "sunday": 1.8,
}

HOURLY_MULTIPLIER: dict[int, float] = {
    0: 0.2,
    1: 0.1,
    2: 0.1,
    3: 0.1,
    4: 0.1,
    5: 0.2,
    6: 0.4,
    7: 0.7,
    8: 1.0,
    9: 1.2,
    10: 1.4,
    11: 1.5,
    12: 1.6,
    13: 1.5,
    14: 1.4,
    15: 1.5,
    16: 1.7,
    17: 2.0,
    18: 2.3,
    19: 2.5,
    20: 2.2,
    21: 1.7,
    22: 1.0,
    23: 0.5,
}


class RateConfig(BaseModel):
    """Per-shop knobs for turning simulated time into arrivals per minute.

    The weekly/daily shape is fixed in the module constants
    (DAY_OF_WEEK_MULTIPLIER / HOURLY_MULTIPLIER). This holds only what varies by
    shop or scenario: the profile, base rate, timezone, and the noise band.
    """

    profile: Literal["curve", "flat"] = "curve"
    """The shape of the rate: does it follow the clock, or hold level?

    Named for the shape rather than the period, and `curve` is the word this
    module already used — the constants below are "shape curves", and the
    scheduler calls its own copy `curve`. `daily` would have named only half of
    it, since the weekday multiplier matters as much as the hour.

    `curve` is the shop being simulated: traffic rises and falls with the hour
    and the weekday, which is what makes the company look like a company.

    `flat` exists for **experiments**. Under `curve`, two campaigns launched four
    hours apart meet different shops — a Tuesday afternoon and a Tuesday night
    differ by more than 5× here — so their results are not comparable, and this
    lab spent a session discovering that the shop's state was often the dominant
    variable. Under `flat` the expected rate is the base rate at any hour of any
    day, and **Poisson is the only source of variation left**: the day-of-week
    multiplier, the hourly multiplier and the uniform noise band are all
    bypassed.

    `flat` describes the *rate*, not the traffic. Arrivals still vary run to run
    — a simulation that produced identical traffic would not be one. What it
    buys is two runs *drawn from the same distribution*, which is what a
    comparison needs.
    """

    base_arrivals_per_minute: float = Field(default=3.0, ge=0)
    timezone: str = "UTC"
    noise_min: float = Field(default=0.8, ge=0)
    noise_max: float = Field(default=1.2, ge=0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_noise_range(self) -> Self:
        if self.noise_max < self.noise_min:
            raise ValueError("noise_max must be >= noise_min")
        return self


def localize(now: datetime, config: RateConfig) -> datetime:
    """Return `now` in the configured timezone."""

    zone = ZoneInfo(config.timezone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def arrivals_per_minute(
    now: datetime,
    config: RateConfig,
    rng: random.Random,
) -> float:
    """Calculate the current arrival rate."""

    if config.profile == "flat":
        # No clock, no noise. The caller still samples Poisson around this, so
        # arrivals vary — but two runs launched hours apart are now drawn from
        # the same distribution, which is what makes them comparable.
        #
        # `rng` is deliberately not touched here. Consuming a draw only in the
        # other branch would make the two profiles diverge in the identity pool
        # and the journey choices as well, so a `flat` run would differ from a
        # `curve` one by more than its arrival rate.
        return config.base_arrivals_per_minute

    local_now = localize(now, config)
    day_name = DAY_NAMES[local_now.weekday()]
    day_multiplier = DAY_OF_WEEK_MULTIPLIER.get(day_name, 1.0)
    hour_multiplier = HOURLY_MULTIPLIER.get(local_now.hour, 1.0)

    if config.noise_min == config.noise_max:
        noise = config.noise_min
    else:
        noise = rng.uniform(config.noise_min, config.noise_max)

    return config.base_arrivals_per_minute * day_multiplier * hour_multiplier * noise


def sample_poisson(lambda_value: float, rng: random.Random) -> int:
    """Sample a Poisson-distributed arrival count for one tick (Knuth's method).

    Exact and cheap at the small per-tick rates this simulator uses (a few
    arrivals per tick).
    """

    if lambda_value <= 0:
        return 0

    limit = math.exp(-lambda_value)
    count = 0
    product = 1.0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1
