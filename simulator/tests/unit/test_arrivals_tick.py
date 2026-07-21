"""The arrivals producer tick, tested as a bare async function with a fake ctx.

`tick` is returned unchanged by the `@scheduler.every` decorator, so it is
callable directly — no runtime, no Redis. The tick reads the wall clock for the
rate curve, so we don't pin an exact count; a huge base rate guarantees the
`max_arrivals_per_tick` cap engages, which makes the emitted count deterministic.
"""

import random

from src.external_flows.contracts import CustomerArrivalEvent
from src.external_flows.customer_arrivals.generation import build_arrival
from src.external_flows.customer_arrivals.identity_pool import IdentityPool
from src.external_flows.customer_arrivals.rate import RateConfig
from src.external_flows.customer_arrivals.scheduler import tick
from src.external_flows.topics import Topic

# Far above any curve point, so the per-tick cap always clamps the count.
HUGE_BASE = 100_000


class FakeContext:
    def __init__(self, resources: dict, config: dict) -> None:
        self.resources = resources
        self.config = config
        self.emitted: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, /, **payload) -> None:
        self.emitted.append((event_type, payload))


def _resources(*, base: float, seed: int = 7) -> dict:
    # One shared RNG, mirroring the lifespan: the pool and the tick draw from it.
    rng = random.Random(seed)
    return {
        "rate": RateConfig(base_arrivals_per_minute=base, noise_min=1.0, noise_max=1.0),
        "identities": IdentityPool(rng=rng),
        "rng": rng,
    }


def _config(**overrides) -> dict:
    base = {"tick_seconds": 5.0}
    base.update(overrides)
    return base


async def test_tick_emits_validatable_customer_arrivals():
    ctx = FakeContext(_resources(base=HUGE_BASE), _config(max_arrivals_per_tick=5))

    await tick(ctx)

    assert len(ctx.emitted) == 5
    for event_type, payload in ctx.emitted:
        assert event_type == Topic.CUSTOMER_ARRIVAL
        event = CustomerArrivalEvent.model_validate(payload)
        assert event.intent.customer.email
        assert event.visitor is not None and event.visitor.ip


async def test_tick_emits_nothing_at_zero_rate():
    ctx = FakeContext(_resources(base=0), _config())

    await tick(ctx)

    assert ctx.emitted == []


async def test_tick_respects_max_arrivals_per_tick():
    ctx = FakeContext(_resources(base=HUGE_BASE), _config(max_arrivals_per_tick=3))

    await tick(ctx)

    assert len(ctx.emitted) == 3


async def test_every_arrival_is_a_fresh_unique_visitor():
    # Each arrival mints a new identity: distinct customers on distinct IPs, so
    # every emission is a distinct visitor to the tracker.
    ctx = FakeContext(_resources(base=HUGE_BASE), _config(max_arrivals_per_tick=10))

    await tick(ctx)

    emails = [p["intent"]["customer"]["email"] for _, p in ctx.emitted]
    ips = [p["visitor"]["ip"] for _, p in ctx.emitted]
    assert len(emails) == 10
    assert len(set(emails)) == 10  # ten distinct customers...
    assert len(set(ips)) == 10  # ...on ten distinct visitor IPs


def test_build_arrival_carries_an_identity_and_intent():
    rng = random.Random(1)
    arrival = build_arrival(IdentityPool(rng=rng), rng)

    assert isinstance(arrival, CustomerArrivalEvent)
    assert arrival.intent.customer.email
    assert arrival.intent.type  # buy_products or browse_discover
    assert arrival.visitor is not None and arrival.visitor.city
