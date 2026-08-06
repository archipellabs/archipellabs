import httpx
import pytest

from roles.blair.tools import shop, tables, workspace
from tests.blair.conftest import transport

DIRECTORY = """<prestashop><api>
<orders get="true" head="true"><description>Orders</description></orders>
<carts get="true"><description>Shopping carts</description></carts>
</api></prestashop>"""
SCHEMA = "<prestashop><order><id/><id_cart/><date_add/></order></prestashop>"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)


def _http(handler, cfg) -> httpx.AsyncClient:
    http = httpx.AsyncClient(base_url=cfg.base_url, transport=transport(handler))
    http.shop_timezone = cfg.timezone  # type: ignore[attr-defined]
    return http


async def test_catalog_and_schema_come_from_the_shop(shop_cfg):
    def handler(request):
        body = SCHEMA if "schema" in request.url.params else DIRECTORY
        return httpx.Response(200, text=body)

    async with _http(handler, shop_cfg) as http:
        catalog = await shop.catalog(http)
        schema = await shop.describe(http, "orders")

    assert [item["resource"] for item in catalog["resources"]] == [
        "carts",
        "orders",
    ]
    assert schema["fields"] == ["id", "id_cart", "date_add"]


async def test_catalog_can_be_searched_and_is_bounded(shop_cfg, monkeypatch):
    monkeypatch.setattr(shop, "MAX_RESOURCES", 1)

    def handler(request):
        return httpx.Response(200, text=DIRECTORY)

    async with _http(handler, shop_cfg) as http:
        first = await shop.catalog(http)
        narrowed = await shop.catalog(http, search="order")

    assert first["returned"] == 1
    assert first["complete"] is False
    assert narrowed["total"] == 1
    assert narrowed["resources"][0]["resource"] == "orders"


async def test_refusal_keeps_the_shops_actionable_message(shop_cfg):
    def handler(request):
        return httpx.Response(
            500,
            json={"errors": [{"message": "Unknown field. Available: id, date_add"}]},
        )

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders", fields=["wrong"])

    assert result["error"] == "Unknown field. Available: id, date_add"
    assert result["http"] == 500


async def test_sort_is_local_then_limit_is_applied(shop_cfg):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        rows = [{"id": str(n)} for n in range(1, 21)]
        return httpx.Response(200, json={"orders": rows})

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders", sort=["id_DESC"], limit=3)

    assert "sort" not in seen[0] and "limit" not in seen[0]
    assert [row["id"] for row in result["rows"]] == ["20", "19", "18"]
    assert result["total"] == 20
    assert result["last_offset"] == 18


async def test_blanks_remain_last_when_sorting_descending(shop_cfg):
    def handler(request):
        return httpx.Response(
            200,
            json={"orders": [{"id": "2"}, {"id": ""}, {"id": "10"}]},
        )

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders", sort=["id_DESC"])

    assert [row["id"] for row in result["rows"]] == ["10", "2", ""]


async def test_saved_query_returns_preview_and_table_receipt(shop_cfg):
    rows = [{"id": n, "payload": "x" * 100} for n in range(50)]

    def handler(request):
        return httpx.Response(200, json={"orders": rows})

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders", save_as="orders")

    assert "rows" not in result
    assert len(result["preview"]) == shop.MAX_PREVIEW
    assert result["table"]["row_count"] == 50
    assert result["table"]["complete"] is True
    assert len(tables.load("orders")) == 50


async def test_saved_limited_query_does_not_claim_a_complete_table(shop_cfg):
    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": n} for n in range(5)]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders", limit=5, save_as="orders")

    assert result["table"]["complete"] == "unknown"


async def test_caller_limited_read_does_not_invent_a_total(shop_cfg):
    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": n} for n in range(5)]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders", limit=5)

    assert result["complete"] == "unknown"
    assert "total" not in result


async def test_shop_timestamps_state_their_timezone(shop_cfg):
    def handler(request):
        return httpx.Response(
            200,
            json={"orders": [{"id": 1, "date_add": "2026-07-31 10:02:00"}]},
        )

    async with _http(handler, shop_cfg) as http:
        result = await shop.query(http, "orders")

    assert result["time_window"]["timezone"] == "America/Chicago"
