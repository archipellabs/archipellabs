"""Component test over a fake Redis: dispatching catalog.sync routes to the
catalog service's action. The PrestaShop sync logic is stubbed — we only assert
the wiring. Hermetic (no live services), so it runs in the default lane."""

import asyncio

from fakeredis.aioredis import FakeRedis
from runtime.broker import Delivery
from runtime.context import Limits, RuntimeContext
from runtime.envelope import make_envelope
from runtime.redis_io import RedisBroker
from runtime.service import slot_worker

from src.internal_flows.catalog import service as catalog_service
from src.internal_flows.catalog import sync as catalog_sync
from src.internal_flows.topics import Topic

REGISTRATION = next(
    r for r in catalog_service.service.consumers if r.name == Topic.CATALOG_SYNC
)


def _broker() -> RedisBroker:
    return RedisBroker(FakeRedis(decode_responses=True))


def _ctx(broker: RedisBroker) -> RuntimeContext:
    return RuntimeContext(
        broker, resources={"json_http": object(), "xml_http": object()}
    )


async def test_catalog_sync_message_routes_to_the_action(monkeypatch):
    calls = []

    async def fake_sync(json_http, xml_http):
        calls.append((json_http, xml_http))
        return {"errors": []}

    monkeypatch.setattr(catalog_sync, "sync_catalog", fake_sync)

    broker = _broker()
    await broker.ensure_group(
        REGISTRATION.stream, REGISTRATION.group, start=REGISTRATION.start
    )
    await broker.append(
        REGISTRATION.stream, make_envelope(kind="dispatch", name=Topic.CATALOG_SYNC), {}
    )

    messages = await broker.claim(
        REGISTRATION.stream, REGISTRATION.group, consumer="c1", count=10, block_ms=50
    )

    assert len(messages) == 1
    [message] = messages
    assert isinstance(message, Delivery)
    summary = await catalog_service.sync(_ctx(broker), message.params)
    await broker.ack(REGISTRATION.stream, REGISTRATION.group, message.id)

    assert len(calls) == 1, "the action ran exactly once for the message"
    assert summary == {"errors": []}
    await broker.aclose()


async def test_a_failing_sync_does_not_stop_the_worker(monkeypatch):
    """A raise is reported and acked — with no reclaim, leaving it pending would
    lose it anyway — and the worker goes on to the next message."""
    calls = 0
    second_handled = asyncio.Event()

    async def fail_then_succeed(json_http, xml_http):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient failure")
        second_handled.set()
        return {"errors": []}

    monkeypatch.setattr(catalog_sync, "sync_catalog", fail_then_succeed)

    broker = _broker()
    await broker.ensure_group(
        REGISTRATION.stream, REGISTRATION.group, start=REGISTRATION.start
    )
    for attempt in (1, 2):
        await broker.append(
            REGISTRATION.stream,
            make_envelope(kind="dispatch", name=Topic.CATALOG_SYNC),
            {"attempt": attempt},
        )

    worker = asyncio.create_task(
        slot_worker(
            broker,
            REGISTRATION,
            service_name="catalog",
            consumer="catalog-test",
            ctx=_ctx(broker),
            semaphore=asyncio.Semaphore(1),
            limits=Limits(),
            block_ms=20,
        )
    )
    try:
        await asyncio.wait_for(second_handled.wait(), timeout=2)
        assert calls == 2
        assert not worker.done()
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await broker.aclose()
