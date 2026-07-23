"""Keep tracked products above a stock floor — top them back up when low.

A small business flow: check each tracked product's Webservice stock and, when it
dips below the low-water mark, set the quantity back to the refill target. Reuses
the catalog's Webservice helpers/clients (one source of truth for PS plumbing).
"""

import logging
from typing import Any

import httpx

from src.internal_flows.catalog import prestashop as ps

log = logging.getLogger("simulator.stock")

# Products (by Webservice `reference`) whose stock is kept topped up.
TRACKED_REFERENCES: tuple[str, ...] = ("barrel", "chest")
LOW_WATER_MARK = 16  # refill once stock dips below this
REFILL_TO = 256  # target quantity after a refill


async def refill_stock(
    json_http: httpx.AsyncClient, xml_http: httpx.AsyncClient
) -> dict[str, Any]:
    """Check the tracked products and refill any below the low-water mark.

    Idempotent: a product already at/above the mark is left untouched.
    """
    checked: list[dict[str, Any]] = []
    refilled: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for reference in TRACKED_REFERENCES:
        pid = await _product_id_by_reference(json_http, reference)
        if pid is None:
            errors.append({"reference": reference, "reason": "product not found"})
            continue

        for sa in await _stock_availables(json_http, pid):
            quantity = int(sa.get("quantity", 0))
            checked.append({"reference": reference, "quantity": quantity})
            if quantity >= LOW_WATER_MARK:
                continue
            if await _set_quantity(xml_http, sa, REFILL_TO):
                refilled.append(
                    {"reference": reference, "from": quantity, "to": REFILL_TO}
                )
                log.info("refilled %s: %d → %d", reference, quantity, REFILL_TO)
            else:
                errors.append({"reference": reference, "reason": "refill failed"})

    return {"checked": checked, "refilled": refilled, "errors": errors}


async def _product_id_by_reference(
    json_http: httpx.AsyncClient, reference: str
) -> int | None:
    r = await json_http.get(
        "/products", params={"filter[reference]": reference, "display": "full"}
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):  # no match → []
        return None
    items = data.get("products", [])
    return int(items[0]["id"]) if items else None


async def _stock_availables(
    json_http: httpx.AsyncClient, product_id: int
) -> list[dict[str, Any]]:
    r = await json_http.get(
        "/stock_availables",
        params={"filter[id_product]": product_id, "display": "full"},
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return []
    return data.get("stock_availables", [])


async def _set_quantity(
    xml_http: httpx.AsyncClient, stock_available: dict[str, Any], quantity: int
) -> bool:
    """PUT a stock_available back with a new quantity, preserving its other fields."""
    body = ps.wrap(
        "stock_available",
        ps.field("id", stock_available["id"]),
        ps.field("id_product", stock_available["id_product"]),
        ps.field(
            "id_product_attribute", stock_available.get("id_product_attribute", 0)
        ),
        ps.field("id_shop", stock_available.get("id_shop", 1)),
        ps.field("id_shop_group", stock_available.get("id_shop_group", 0)),
        ps.field("depends_on_stock", stock_available.get("depends_on_stock", 0)),
        ps.field("out_of_stock", stock_available.get("out_of_stock", 2)),
        ps.field("quantity", quantity),
    )
    return await ps.put(xml_http, "stock_availables", int(stock_available["id"]), body)
