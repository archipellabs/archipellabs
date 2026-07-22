"""Stock refill against a live PrestaShop (Webservice API). Run on demand:

    uv run pytest tests/e2e/test_stock.py

Tops up the tracked products (barrel, chest) to REFILL_TO when below the floor.
Idempotent: a second pass finds nothing to refill.
"""

import pytest

from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.stock.refill import (
    LOW_WATER_MARK,
    TRACKED_REFERENCES,
    refill_stock,
)

pytestmark = pytest.mark.e2e


async def test_stock_refill_tops_up_low_products():
    async with json_client() as json_http, xml_client() as xml_http:
        first = await refill_stock(json_http, xml_http)
        second = await refill_stock(json_http, xml_http)

    assert first["errors"] == []
    # both tracked products were found and checked
    assert {c["reference"] for c in first["checked"]} == set(TRACKED_REFERENCES)
    # after one pass everything sits at/above the floor → second pass is a no-op
    assert second["refilled"] == []
    assert all(c["quantity"] >= LOW_WATER_MARK for c in second["checked"])
