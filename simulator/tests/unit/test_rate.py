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


# ── the flat profile, for experiments ────────────────────────────────────────


def test_flat_ignores_the_hour_and_the_weekday():
    """The reason it exists. Under the curve, two campaigns launched hours
    apart meet shops differing by more than 5x, so their results cannot be
    compared — and in this lab the shop's state has more than once turned out to
    be the dominant variable in a measurement."""
    config = RateConfig(profile="flat", base_arrivals_per_minute=3.0)
    rng = random.Random(0)

    quiet = arrivals_per_minute(datetime(2026, 7, 27, 3, tzinfo=UTC), config, rng)
    busy = arrivals_per_minute(datetime(2026, 8, 1, 19, tzinfo=UTC), config, rng)

    assert quiet == busy == 3.0


def test_the_curve_profile_still_moves_with_the_clock():
    """The shop being simulated is a shop. `flat` is the exception, not a
    replacement."""
    config = RateConfig(profile="curve", base_arrivals_per_minute=3.0)
    rng = random.Random(0)

    quiet = arrivals_per_minute(datetime(2026, 7, 27, 3, tzinfo=UTC), config, rng)
    busy = arrivals_per_minute(datetime(2026, 8, 1, 19, tzinfo=UTC), config, rng)

    assert busy > quiet * 5


def test_flat_leaves_poisson_as_the_only_variation():
    """Not merely the clock: the uniform noise band is bypassed too. A rate that
    still jittered would make two runs differ by something other than the
    sampling that is meant to be the whole difference."""
    config = RateConfig(
        profile="flat", base_arrivals_per_minute=3.0, noise_min=0.1, noise_max=9.0
    )
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)

    rates = {arrivals_per_minute(now, config, random.Random(seed)) for seed in range(20)}

    assert rates == {3.0}


def test_flat_does_not_consume_the_shared_rng():
    """The rate is not the only thing drawn from this generator — the identity
    pool and the journey choices share it. Spending a draw in one profile and
    not the other would make a flat run differ from a curve one by more than
    its arrival rate."""
    config = RateConfig(profile="flat", base_arrivals_per_minute=3.0)
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)

    untouched, used = random.Random(7), random.Random(7)
    arrivals_per_minute(now, config, used)

    assert untouched.random() == used.random()


def test_flat_still_varies_run_to_run_through_poisson():
    """It is a fixed expectation, not a fixed count. Two campaigns are drawn
    from the same distribution, which is what a comparison needs — a simulation
    that produced identical traffic would not be one."""
    config = RateConfig(profile="flat", base_arrivals_per_minute=3.0)
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)

    counts = {
        sample_poisson(arrivals_per_minute(now, config, rng), rng)
        for rng in (random.Random(seed) for seed in range(30))
    }

    assert len(counts) > 1
