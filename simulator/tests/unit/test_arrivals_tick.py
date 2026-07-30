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
from tests.conftest import use_overrides

# Far above any curve point, so the per-tick cap always clamps the count.
HUGE_BASE = 100_000


class FakeContext:
    def __init__(self, resources: dict) -> None:
        self.resources = resources
        self.emitted: list[tuple[str, dict]] = []
        self.ttls: list[str | float | None] = []

    async def dispatch(self, action: str, /, *, ttl=None, **payload) -> str:
        self.emitted.append((action, payload))
        self.ttls.append(ttl)
        return "task-id"


def _resources(seed: int = 7) -> dict:
    # One shared RNG, mirroring the lifespan: the pool and the tick draw from it.
    # The lifespan's RateConfig carries only the curve's shape — the base rate is
    # a tunable the tick reads from the configuration each pass.
    rng = random.Random(seed)
    return {
        "rate": RateConfig(noise_min=1.0, noise_max=1.0),
        "identities": IdentityPool(rng=rng),
        "rng": rng,
    }


async def test_tick_emits_validatable_customer_arrivals():
    await use_overrides(base_arrivals_per_minute=HUGE_BASE, max_arrivals_per_tick=5)
    ctx = FakeContext(_resources())

    await tick(ctx)

    assert len(ctx.emitted) == 5
    for event_type, payload in ctx.emitted:
        assert event_type == Topic.CUSTOMER_ARRIVAL
        event = CustomerArrivalEvent.model_validate(payload)
        assert event.intent.customer.email
        assert event.visitor is not None and event.visitor.ip


async def test_tick_emits_nothing_at_zero_rate():
    await use_overrides(base_arrivals_per_minute=0)
    ctx = FakeContext(_resources())

    await tick(ctx)

    assert ctx.emitted == []


async def test_tick_respects_max_arrivals_per_tick():
    await use_overrides(base_arrivals_per_minute=HUGE_BASE, max_arrivals_per_tick=3)
    ctx = FakeContext(_resources())

    await tick(ctx)

    assert len(ctx.emitted) == 3


async def test_every_arrival_is_a_fresh_unique_visitor():
    # Each arrival mints a new identity: distinct customers on distinct IPs, so
    # every emission is a distinct visitor to the tracker.
    await use_overrides(base_arrivals_per_minute=HUGE_BASE, max_arrivals_per_tick=10)
    ctx = FakeContext(_resources())

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
