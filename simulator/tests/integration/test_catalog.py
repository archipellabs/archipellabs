"""Catalog sync against a live PrestaShop (Webservice API).

Requires the e-commerce stack up with the Webservice API key provisioned. Run on
demand (the `integration` marker is deselected by default):

    uv run pytest tests/integration/test_catalog.py

`sync` is purely additive and idempotent: it creates/patches to match the PIM
and never deletes, so re-running skips what already matches. Clearing the
install's demo catalogue is provisioning's job (the sidecar PurgeDemoData step),
not the simulator's.
"""

import pytest

from src.internal_flows.catalog import prestashop as ps
from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.catalog.sync import sync_catalog

pytestmark = pytest.mark.integration


async def test_catalog_sync():
    async with json_client() as json_http, xml_client() as xml_http:
        summary = await sync_catalog(json_http, xml_http)
        products = await ps.get_all(json_http, "products")

    assert summary["errors"] == []
    assert summary["categories"] >= 1
    assert len(products) >= 1


async def test_catalog_sync_is_idempotent():
    """A second pass creates nothing new — everything matches by name."""
    async with json_client() as json_http, xml_client() as xml_http:
        await sync_catalog(json_http, xml_http)
        summary = await sync_catalog(json_http, xml_http)

    assert summary["errors"] == []
    assert summary["products_created"] == 0
