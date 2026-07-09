"""run_arrival tested with a fake ctx and a monkeypatched journey runner.

The flow handler is returned unchanged by `@pool.flow`, so it is callable
directly. We stub `run_customer_journey` to avoid driving a real browser, and
assert the wiring: validate → adapter → new_context → run → close.
"""

from src.external_flows.contracts import (
    CustomerArrivalEvent,
    CustomerIntent,
    CustomerIntentType,
    CustomerProfile,
    ProductIntent,
)
from src.external_flows.customer_journey import pool as pool_module
from src.external_flows.customer_journey.pool import run_arrival


class FakeBrowserContext:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeBrowserContext] = []

    async def new_context(self, **kwargs) -> FakeBrowserContext:
        ctx = FakeBrowserContext()
        self.contexts.append(ctx)
        return ctx


class ExplodingBrowser:
    async def new_context(self, **kwargs):
        raise AssertionError("browser must not be touched for a malformed event")


class FakeCtx:
    def __init__(self, resources: dict, config: dict | None = None) -> None:
        self.resources = resources
        self.config: dict = config if config is not None else {}

    async def emit(self, event_type: str, /, **payload) -> None: ...


def _valid_event(n_products: int = 1) -> dict:
    profile = CustomerProfile(
        firstname="A",
        lastname="B",
        email="a.b@example.com",
        address1="1 Street",
        city="Town",
        postcode="12345",
        phone="",
        country="US",
    )
    event = CustomerArrivalEvent.create(
        intent=CustomerIntent(
            type=CustomerIntentType.BUY_PRODUCTS,
            customer=profile,
            products=[
                ProductIntent(category="X", quantity=1) for _ in range(n_products)
            ],
        ),
    )
    return event.model_dump(mode="json")


async def test_run_arrival_runs_journey_and_closes_context(monkeypatch):
    captured: dict = {}

    async def fake_journey(context, base_url, *, journey, guest, fast, flow_id, **kw):
        captured.update(
            context=context,
            base_url=base_url,
            journey=journey,
            guest=guest,
            fast=fast,
            flow_id=flow_id,
        )

    monkeypatch.setattr(pool_module, "run_customer_journey", fake_journey)
    browser = FakeBrowser()
    ctx = FakeCtx({"browser": browser}, {"base_url": "https://shop.test", "fast": True})

    event = _valid_event(n_products=1)
    await run_arrival(ctx, event)

    assert captured["journey"] == "guest_checkout"
    assert captured["base_url"] == "https://shop.test"
    assert captured["guest"].email == "a.b@example.com"
    assert captured["flow_id"] == event["id"]  # consumer traces under the arrival id
    assert browser.contexts and browser.contexts[0].closed is True


async def test_run_arrival_drops_malformed_event(monkeypatch):
    called = False

    async def fake_journey(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(pool_module, "run_customer_journey", fake_journey)
    ctx = FakeCtx({"browser": ExplodingBrowser()})

    # Must not raise, must not touch the browser, must not run a journey.
    await run_arrival(ctx, {"not": "a valid event"})

    assert called is False
