"""The bound on the settlement query.

There is an e2e suite for this flow (`tests/e2e/test_payments.py`) and it passed
throughout: it drives a shop with a handful of waiting orders, where the bug
below is invisible. What broke was a property that only appears at size, so it
belongs in a test that can state the size without needing a shop to reach it.
"""

import httpx
import pytest

from src.internal_flows.payments.accept import (
    MAX_PER_PASS,
    accept_bank_wire_payments,
)


@pytest.mark.asyncio
async def test_the_settlement_query_asks_for_only_what_it_will_use() -> None:
    """The regression: it asked for the whole backlog and then used 25 of it.

    On the public deployment the awaiting set reached 50 223 orders. PrestaShop
    could not serialise that inside the read timeout, so the call raised
    `httpx.ReadTimeout` and settled nothing — and because a failed pass leaves
    the backlog untouched while new orders keep arriving, the next request was
    always larger than the one that had just timed out. Every order the shop had
    ever taken sat in *Awaiting bank wire payment*.

    Asserting on the request rather than on the outcome, because the outcome was
    never wrong — it was unreachable.
    """
    seen: list[httpx.URL] = []

    def shop(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/orders") and request.method == "GET":
            return httpx.Response(200, json={"orders": [{"id": 1}]})
        return httpx.Response(200, text="<prestashop/>")

    transport = httpx.MockTransport(shop)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://shop.test/api") as j,
        httpx.AsyncClient(transport=transport, base_url="https://shop.test/api") as x,
    ):
        await accept_bank_wire_payments(j, x)

    listing = next(u for u in seen if u.path.endswith("/orders"))
    assert listing.params.get("limit") == str(MAX_PER_PASS), (
        f"the settlement listing is unbounded: {listing}"
    )


@pytest.mark.asyncio
async def test_an_empty_backlog_settles_nothing_rather_than_failing() -> None:
    """PrestaShop answers a bare `[]` when a filter matches nothing, and
    `{"orders": [...]}` when it matches something — the shape changes with the
    count, so the empty case is its own path."""
    def shop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(shop)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://shop.test/api") as j,
        httpx.AsyncClient(transport=transport, base_url="https://shop.test/api") as x,
    ):
        summary = await accept_bank_wire_payments(j, x)

    assert summary == {"waiting": 0, "accepted": [], "errors": []}
