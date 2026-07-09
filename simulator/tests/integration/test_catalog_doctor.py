"""Catalog doctor + additive sync against a live PrestaShop. Run on demand:

    uv run pytest tests/integration/test_catalog_doctor.py

The sync is additive-only, so the doctor's contract is: ignore EXTRA live items
(removing them is provisioning's job, not the simulator's) and flag MISSING ones
so the sync re-creates them. Leaves the catalogue converged.
"""

import pytest

from src.internal_flows.catalog import prestashop as ps
from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.catalog.doctor import _detect_drift
from src.internal_flows.catalog.sync import HOME_CATEGORY_ID, sync_catalog

pytestmark = pytest.mark.integration


async def test_doctor_ignores_extra_category():
    async with json_client() as json_http, xml_client() as xml_http:
        await sync_catalog(json_http, xml_http)
        assert await _detect_drift(json_http) is None

        # A stray EXTRA category must NOT trigger drift: the sync is additive and
        # never deletes, so flagging extras would just thrash the reconcile loop.
        stray_id = ps.resource_id(
            await ps.post(
                xml_http,
                "categories",
                ps.wrap(
                    "category",
                    ps.field("active", 1),
                    ps.field("id_parent", HOME_CATEGORY_ID),
                    ps.lang("name", "Stray Test Category"),
                    ps.lang("link_rewrite", "stray-test-category"),
                ),
            )
        )
        assert stray_id is not None
        try:
            assert await _detect_drift(json_http) is None
        finally:
            await xml_http.delete(f"/categories/{stray_id}")


async def test_doctor_detects_missing_and_sync_recreates():
    async with json_client() as json_http, xml_client() as xml_http:
        await sync_catalog(json_http, xml_http)

        # Remove an expected category to simulate it going missing upstream.
        target = next(
            c
            for c in await ps.get_all(json_http, "categories")
            if str(c.get("id_parent")) == str(HOME_CATEGORY_ID)
        )
        await xml_http.delete(f"/categories/{target['id']}")
        assert await _detect_drift(json_http) is not None

        # The additive sync re-creates the missing category and converges.
        summary = await sync_catalog(json_http, xml_http)
        assert summary["errors"] == []
        assert await _detect_drift(json_http) is None
