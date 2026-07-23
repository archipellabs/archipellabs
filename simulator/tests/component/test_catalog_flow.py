"""Component test over a fake Redis: emitting catalog.sync routes to the catalog
pool's handler. The PrestaShop sync logic is stubbed — we only assert the wiring
(event → handler). Hermetic (no live services), so it runs in the default lane."""

import asyncio

from fakeredis.aioredis import FakeRedis
from runtime.broker import stream_name
from runtime.context import RuntimeContext
from runtime.pool import slot_worker
from runtime.redis_io import RedisBroker

from src.internal_flows.catalog import pool as catalog_pool
from src.internal_flows.catalog import sync as catalog_sync
from src.internal_flows.topics import Topic


def _ctx(broker: RedisBroker) -> RuntimeContext:
    return RuntimeContext(
        broker, resources={"json_http": object(), "xml_http": object()}
    )


async def test_catalog_sync_event_routes_to_sync_handler(monkeypatch):
    calls = []

    async def fake_sync(json_http, xml_http):
        calls.append((json_http, xml_http))
        return {"errors": []}

    monkeypatch.setattr(catalog_sync, "sync_catalog", fake_sync)

    broker = RedisBroker(FakeRedis(decode_responses=True))
    stream = stream_name(Topic.CATALOG_SYNC)
    await broker.ensure_stream(stream)
    await broker.append(stream, {})

    ctx = _ctx(broker)
    msgs = await broker.claim(stream, consumer="c1", count=10, block_ms=50)
    assert len(msgs) == 1
    for msg_id, event in msgs:
        await catalog_pool.sync(ctx, event)
        await broker.ack(stream, msg_id)

    assert len(calls) == 1
    await broker.aclose()


async def test_catalog_handler_exception_does_not_kill_runtime_worker(monkeypatch):
    """Runtime catches a failed sync, leaves it pending, then handles the next event."""
    calls = 0
    second_handled = asyncio.Event()

    async def fail_then_succeed(json_http, xml_http):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"errors": [{"reason": "transient failure"}]}
        second_handled.set()
        return {"errors": []}

    monkeypatch.setattr(catalog_sync, "sync_catalog", fail_then_succeed)

    broker = RedisBroker(FakeRedis(decode_responses=True))
    stream = stream_name(Topic.CATALOG_SYNC)
    await broker.ensure_stream(stream)
    await broker.append(stream, {"attempt": 1})
    await broker.append(stream, {"attempt": 2})

    worker = asyncio.create_task(
        slot_worker(
            broker,
            catalog_pool.sync,
            consumes=Topic.CATALOG_SYNC,
            consumer="catalog-test",
            resources={"json_http": object(), "xml_http": object()},
            config={},
            pool_sem=asyncio.Semaphore(1),
        )
    )
    try:
        await asyncio.wait_for(second_handled.wait(), timeout=1)
        assert calls == 2
        assert not worker.done()
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await broker.aclose()
