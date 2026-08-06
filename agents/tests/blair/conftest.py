from collections.abc import Callable

import httpx
import pytest

from core.config import LokiConfig, MatomoConfig, ShopConfig

Handler = Callable[[httpx.Request], httpx.Response]


def transport(handler: Handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.fixture
def shop_cfg() -> ShopConfig:
    return ShopConfig("https://shop.test/api", "key", "America/Chicago")


@pytest.fixture
def matomo_cfg() -> MatomoConfig:
    return MatomoConfig("https://tracking.test", "token", "1")


@pytest.fixture
def loki_cfg() -> LokiConfig:
    return LokiConfig("https://logs.test")
