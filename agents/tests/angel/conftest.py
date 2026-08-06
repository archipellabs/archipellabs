"""Hermetic scaffolding: a fake HTTP transport and the configs the tools take.

The live suite (`-m live`) proves the tools agree with the real PrestaShop and
Matomo. These fakes prove the tools behave correctly on responses those systems
*can* produce but rarely do on a healthy stack — a 500, a truncated body, an
error delivered with HTTP 200. Those are the paths that fabricated a root cause,
and they are unreachable from a working shop.
"""

from collections.abc import Callable

import httpx
import pytest

from core.config import LokiConfig, MatomoConfig, ShopConfig

Handler = Callable[[httpx.Request], httpx.Response]


def transport(handler: Handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def json_route(payload: object, status: int = 200) -> Handler:
    """Every request gets the same JSON. Enough for single-call assertions."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handle


@pytest.fixture
def shop_cfg() -> ShopConfig:
    return ShopConfig(
        base_url="https://shop.test/api", api_key="k", timezone="America/Chicago"
    )


@pytest.fixture
def matomo_cfg() -> MatomoConfig:
    return MatomoConfig(base_url="https://tracking.test", token="t", site_id="1")


@pytest.fixture
def loki_cfg() -> LokiConfig:
    return LokiConfig(base_url="https://loki.test")
