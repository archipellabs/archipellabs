"""Component test over a fake Redis: a producer tick dispatches arrivals onto the
stream, and the consumer's `run_arrival` processes the round-tripped messages. No
real Redis, no real browser — the journey runner is stubbed. Hermetic, so it runs
in the default lane (not the e2e marker).

The validation step below is what the runtime does for us in production, because
the action declares `params=CustomerArrivalEvent`."""

import random

from fakeredis.aioredis import FakeRedis
from runtime.broker import Delivery
from runtime.context import RuntimeContext
from runtime.redis_io import RedisBroker

from src.external_flows.contracts import CustomerArrivalEvent
from src.external_flows.customer_arrivals.identity_pool import IdentityPool
from src.external_flows.customer_arrivals.rate import RateConfig
from src.external_flows.customer_arrivals.scheduler import tick
from src.external_flows.customer_journey import pool as pool_module
from src.external_flows.customer_journey.pool import run_arrival
from src.external_flows.topics import Topic

REGISTRATION = next(
    r for r in pool_module.service.consumers if r.name == Topic.CUSTOMER_ARRIVAL
)


class FakeBrowserContext:
    async def add_init_script(self, script: str) -> None: ...

    async def close(self) -> None: ...


class FakeBrowser:
    def __init__(self) -> None:
        self.opened = 0

    async def new_context(self, **kwargs) -> FakeBrowserContext:
        self.opened += 1
        return FakeBrowserContext()


class FakeActivityRepository:
    """No-op recorder — the pool lifespan always wires one, so the consumer ctx does too."""

    async def record(self, *, arrival, summary) -> None: ...


def _rate(base: float) -> RateConfig:
    return RateConfig(base_arrivals_per_minute=base, noise_min=1.0, noise_max=1.0)


async def test_arrival_flows_producer_to_consumer(monkeypatch):
    broker = RedisBroker(FakeRedis(decode_responses=True))
    stream = REGISTRATION.stream
    await broker.ensure_group(stream, REGISTRATION.group, start=REGISTRATION.start)

    # ── producer: one tick emits arrivals onto the stream ──
    rng = random.Random(1)
    producer_ctx = RuntimeContext(
        broker,
        resources={
            "rate": _rate(100_000),
            "identities": IdentityPool(rng=rng),
            "rng": rng,
        },
        config={"tick_seconds": 5.0, "max_arrivals_per_tick": 5},
    )
    await tick(producer_ctx)

    # ── consumer: claim the round-tripped events and run the handler ──
    ran: list[dict] = []

    async def fake_journey(browser_context, base_url, *, journey, guest, fast, flow_id):
        ran.append(
            {
                "base_url": base_url,
                "journey": journey,
                "email": guest.email,
                "flow_id": flow_id,
            }
        )

    monkeypatch.setattr(pool_module, "run_customer_journey", fake_journey)

    browser = FakeBrowser()
    consumer_ctx = RuntimeContext(
        broker,
        resources={"browser": browser, "activity_repository": FakeActivityRepository()},
        config={"base_url": "https://shop.test", "fast": True},
    )

    msgs = await broker.claim(
        stream, REGISTRATION.group, consumer="c1", count=10_000, block_ms=50
    )
    assert len(msgs) == 5  # deterministic: huge base + per-tick cap
    for message in msgs:
        assert isinstance(message, Delivery)
        # The runtime validates this before the handler in production; here we
        # stand in for it, which also asserts the payload survives the round trip.
        arrival = CustomerArrivalEvent.model_validate(message.params)
        await run_arrival(consumer_ctx, arrival)
        await broker.ack(stream, REGISTRATION.group, message.id)

    assert len(ran) == len(msgs)
    assert browser.opened == len(msgs)
    assert all(r["base_url"] == "https://shop.test" for r in ran)
    # The consumer traces each run under the arrival id (greppable end-to-end).
    assert all(r["flow_id"].startswith("a_") for r in ran)

    await broker.aclose()
