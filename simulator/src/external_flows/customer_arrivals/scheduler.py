"""customer_arrivals — producer of Topic.CUSTOMER_ARRIVAL.

The service's lifespan owns the run's shared state — a single RNG, the rate model,
and the identity pool (SERVICE scope, shared across ticks). Each tick samples how
many customers arrive (rate × Poisson) and dispatches one CUSTOMER_ARRIVAL per
arrival — the consumer shares only the name, never a reference.

`dispatch`, not `emit`: an arrival is an instruction with exactly one correct
executant. Driving the same simulated customer twice would place a duplicate
order. `emit` would fan it out to every subscriber.
"""

import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from runtime import Config, Context, Resources, Service

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

STALE_AFTER_TICKS = 4
"""How many ticks an undelivered arrival stays worth simulating. Generous enough
to absorb a brief backlog, short enough that a long outage sheds its queue
instead of replaying an hour of traffic at once when capacity returns."""


@asynccontextmanager
async def arrivals_lifespan(config: Config) -> AsyncIterator[Resources]:
    rng = random.Random(config.get("random_seed"))
    rate = RateConfig(**config.get("rate", {}))
    identities = IdentityPool(rng=rng, markets=config.get("market_mix"))
    yield {"rate": rate, "identities": identities, "rng": rng}


service = Service("customer-arrivals", lifespan=arrivals_lifespan)


@service.every(settings.tick_seconds)
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

    # An arrival is only worth simulating while it is fresh. If the journey
    # service is saturated, one queued several ticks ago is stale traffic: it
    # would distort the load profile it exists to produce, so let it expire at
    # claim time rather than run late.
    ttl = ctx.config["tick_seconds"] * STALE_AFTER_TICKS

    for _ in range(count):
        event = build_arrival(identities, rng)
        await ctx.dispatch(
            Topic.CUSTOMER_ARRIVAL, ttl=ttl, **event.model_dump(mode="json")
        )
    if count:
        log.info("dispatched %d arrival(s)", count)
