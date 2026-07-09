import random
from datetime import UTC, datetime

from pydantic import ValidationError

from src.external_flows.customer_arrivals.rate import (
    DAY_OF_WEEK_MULTIPLIER,
    HOURLY_MULTIPLIER,
    RateConfig,
    arrivals_per_minute,
    sample_poisson,
)


def test_arrivals_per_minute_composes_day_hour_and_noise():
    config = RateConfig(
        base_arrivals_per_minute=10,
        timezone="UTC",
        noise_min=1.0,
        noise_max=1.0,
    )

    now = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)  # Monday, noon
    expected = 10 * DAY_OF_WEEK_MULTIPLIER["monday"] * HOURLY_MULTIPLIER[12] * 1.0

    assert arrivals_per_minute(now, config, random.Random()) == expected


def test_sample_poisson_returns_zero_for_zero_rate():
    assert sample_poisson(0, random.Random()) == 0


def test_rate_config_rejects_invalid_timezone():
    try:
        RateConfig(timezone="Not/AZone")
    except ValidationError as exc:
        assert "unknown timezone" in str(exc)
    else:
        raise AssertionError("RateConfig should reject invalid timezones")
