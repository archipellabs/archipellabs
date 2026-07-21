"""customer_arrivals — producer (Scheduler) of Topic.CUSTOMER_ARRIVAL.

The scheduler's lifespan owns the run's shared state — a single RNG, the rate
model, and the identity pool (POOL scope, shared across ticks). Each tick samples
how many customers arrive (rate × Poisson) and emits one CUSTOMER_ARRIVAL per
arrival — the consumer shares only the event type, never a reference.
"""

import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from runtime import Config, Context, Resources, Scheduler

from src.config import settings
from src.external_flows.customer_arrivals.generation import build_arrival
from src.external_flows.customer_arrivals.identity_pool import IdentityPool
from src.external_flows.customer_arrivals.rate import (
    RateConfig,
    arrivals_per_minute,
    sample_poisson,
)
from src.external_flows.topics import Topic

log = logging.getLogger("simulator.customer_arrivals")

DEFAULT_MAX_ARRIVALS_PER_TICK = 1000


@asynccontextmanager
async def arrivals_lifespan(config: Config) -> AsyncIterator[Resources]:
    rng = random.Random(config.get("random_seed"))
    rate = RateConfig(**config.get("rate", {}))
    identities = IdentityPool(rng=rng, country=config.get("country", "US"))
    yield {"rate": rate, "identities": identities, "rng": rng}


scheduler = Scheduler("customer-arrivals", lifespan=arrivals_lifespan)


@scheduler.every(settings.tick_seconds)
async def tick(ctx: Context) -> None:
    rate: RateConfig = ctx.resources["rate"]
    identities: IdentityPool = ctx.resources["identities"]
    rng: random.Random = ctx.resources["rng"]
    max_per_tick: int = ctx.config.get(
        "max_arrivals_per_tick", DEFAULT_MAX_ARRIVALS_PER_TICK
    )

    per_minute = arrivals_per_minute(datetime.now(UTC), rate, rng)
    expected = per_minute * (ctx.config["tick_seconds"] / 60)
    count = min(sample_poisson(expected, rng), max_per_tick)

    for _ in range(count):
        event = build_arrival(identities, rng)
        await ctx.emit(Topic.CUSTOMER_ARRIVAL, **event.model_dump(mode="json"))
    if count:
        log.info("emitted %d arrival(s)", count)
