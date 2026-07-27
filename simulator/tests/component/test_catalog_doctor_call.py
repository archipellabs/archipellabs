"""The doctor → call → sync round trip, over a fake Redis.

This is the behaviour the 0.3 migration exists for, and until this test it was
only ever verified by running the app by hand: the doctor `call`s the sync action
and gets the *summary back*, rather than inferring failure from an exception it
never sees.

It runs the real `App` wiring — one service holding both the action and the
producer that calls it — so it also covers what makes that safe: a producer holds
no slot permit, and can therefore call into its own service's single slot without
deadlocking.
"""

import asyncio
from contextlib import asynccontextmanager

from fakeredis.aioredis import FakeRedis
from runtime import App, Service
from runtime.redis_io import RedisBroker

from src.internal_flows.catalog import service as catalog_service
from src.internal_flows.catalog import sync as catalog_sync
from src.internal_flows.topics import Topic


@asynccontextmanager
async def _fake_clients(config):
    yield {"json_http": object(), "xml_http": object()}


class _FakeJsonClient:
    """Stands in for `json_client()` in the doctor's drift check."""

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return None


async def _no_drift(http):
    return None


def _build(monkeypatch) -> App:
    """The real service functions, with the network stubbed.

    The service is reassembled here rather than imported, because the doctor is
    registered at import time behind a settings flag — this keeps the test
    independent of the ambient .env.
    """
    monkeypatch.setattr(catalog_service, "json_client", _FakeJsonClient)
    monkeypatch.setattr(catalog_service, "_detect_drift", _no_drift)

    service = Service("catalog", max_slots=1, lifespan=_fake_clients)
    service.register_action(catalog_service.sync, name=Topic.CATALOG_SYNC)
    service.register_every(
        catalog_service.doctor, interval="0.05s", id="catalog-doctor"
    )

    app = App(redis="unused://", claim_block="0.05s", switch_interval=0.02)
    app.include(service)
    return app


async def _serve_until_logged(app, broker, caplog, needle: str, timeout: float = 10.0):
    """Run until the doctor has logged its verdict — not merely until the sync
    started, which would race the very thing under test."""
    task = asyncio.create_task(app._serve(broker))
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if needle in caplog.text:
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"never logged {needle!r}; got:\n{caplog.text}")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_the_doctor_receives_a_clean_sync_summary(monkeypatch, caplog):
    async def clean_sync(json_http, xml_http):
        return {"errors": [], "products_created": 3}

    monkeypatch.setattr(catalog_sync, "sync_catalog", clean_sync)
    broker = RedisBroker(FakeRedis(decode_responses=True))

    with caplog.at_level("INFO", logger="simulator.catalog"):
        await _serve_until_logged(
            _build(monkeypatch), broker, caplog, "catalog sync complete"
        )

    await broker.aclose()


async def test_the_doctor_reports_an_incomplete_sync(monkeypatch, caplog):
    """Under 0.2 the action raised to make this visible and the doctor never saw
    it. The errors now travel back to the caller as a value."""

    async def failing_sync(json_http, xml_http):
        return {"errors": [{"name": "Chest", "reason": "patch failed"}]}

    monkeypatch.setattr(catalog_sync, "sync_catalog", failing_sync)
    broker = RedisBroker(FakeRedis(decode_responses=True))

    with caplog.at_level("INFO", logger="simulator.catalog"):
        await _serve_until_logged(
            _build(monkeypatch), broker, caplog, "catalog sync incomplete"
        )

    assert "patch failed" in caplog.text
    await broker.aclose()
