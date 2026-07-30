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

from src.external_flows.customer_arrivals.generation import build_arrival
from src.external_flows.customer_arrivals.identity_pool import IdentityPool
from src.external_flows.customer_arrivals.rate import (
    RateConfig,
    arrivals_per_minute,
    sample_poisson,
)
from src.external_flows.topics import Topic
from src.services.configuration.service import configuration

log = logging.getLogger("simulator.customer_arrivals")

STALE_AFTER_TICKS = 4
"""How many ticks an undelivered arrival stays worth simulating. Generous enough
to absorb a brief backlog, short enough that a long outage sheds its queue
instead of replaying an hour of traffic at once when capacity returns."""


@asynccontextmanager
async def arrivals_lifespan(config: Config) -> AsyncIterator[Resources]:
    # Warm the configuration snapshot before the first tick, so a run starts on
    # the stored values rather than spending one pass on the defaults.
    await configuration.refresh()

    rng = random.Random(configuration.get("random_seed"))
    # The shape of the curve — timezone and noise band — is fixed for the run. The
    # base rate rides on top of it and is re-read every tick, so it is left at the
    # model's default here rather than seeded from a second source.
    rate = RateConfig(timezone=configuration.get("arrival_timezone"))
    identities = IdentityPool(rng=rng, markets=configuration.get("market_mix"))
    yield {"rate": rate, "identities": identities, "rng": rng}


service = Service("customer-arrivals", lifespan=arrivals_lifespan)


@service.every(configuration.get("tick_seconds"))
async def tick(ctx: Context) -> None:
    identities: IdentityPool = ctx.resources["identities"]
    rng: random.Random = ctx.resources["rng"]

    # Re-read every tick, so a change lands without a restart. Answered from the
    # configuration snapshot, so this is a dict lookup rather than a query.
    identities.set_market_mix(configuration.get("market_mix"))
    rate: RateConfig = ctx.resources["rate"].model_copy(
        update={
            "base_arrivals_per_minute": configuration.get("base_arrivals_per_minute")
        }
    )

    tick_seconds: float = configuration.get("tick_seconds")
    per_minute = arrivals_per_minute(datetime.now(UTC), rate, rng)
    expected = per_minute * (tick_seconds / 60)
    count = min(
        sample_poisson(expected, rng), configuration.get("max_arrivals_per_tick")
    )

    # An arrival is only worth simulating while it is fresh. If the journey
    # service is saturated, one queued several ticks ago is stale traffic: it
    # would distort the load profile it exists to produce, so let it expire at
    # claim time rather than run late.
    ttl = tick_seconds * STALE_AFTER_TICKS

    for _ in range(count):
        event = build_arrival(identities, rng)
        await ctx.dispatch(
            Topic.CUSTOMER_ARRIVAL, ttl=ttl, **event.model_dump(mode="json")
        )
    if count:
        log.info("dispatched %d arrival(s)", count)
