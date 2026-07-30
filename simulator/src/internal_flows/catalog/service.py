"""catalog — one service: the sync action, and the doctor that asks for it.

These were two files under 0.2 purely because one consumed and one produced. They
are one domain, and now one service: the doctor `call`s the sync and *gets the
summary back*, so a failed reconciliation is a value it can read and log rather
than something inferred from an exception.

`max_slots=1` serialises catalog operations — they mutate the same shop and must
not overlap. The doctor is a producer and holds no slot, so calling into its own
service's single slot is safe; and because `run_every` awaits the call, a sync
running longer than the interval simply delays the next check instead of stacking
a second one on top.

The sync is purely additive (it never deletes) — clearing install demo data is a
setup-time concern owned by provisioning, not the simulator. To run the sync
directly against a live shop, see `tests/integration/test_catalog.py`.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from runtime import Config, Context, Params, Resources, Service

from src.internal_flows.catalog import prestashop as ps
from src.internal_flows.catalog import sync as catalog_sync
from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.catalog.sync import HOME_CATEGORY_ID, load_pim
from src.internal_flows.topics import Topic
from src.services.configuration.service import configuration

log = logging.getLogger("simulator.catalog")

SYNC_TTL = "15m"
"""How long a reconcile stays worth doing. A full idempotent pass over the
catalogue is slow, so this is generous — but bounded, so a wedged sync releases
the doctor instead of blocking the schedule forever."""


@asynccontextmanager
async def prestashop_lifespan(config: Config) -> AsyncIterator[Resources]:
    json_http = json_client()
    xml_http = xml_client()
    try:
        yield {"json_http": json_http, "xml_http": xml_http}
    finally:
        await json_http.aclose()
        await xml_http.aclose()


service = Service("catalog", max_slots=1, lifespan=prestashop_lifespan)


@service.action(Topic.CATALOG_SYNC)
async def sync(ctx: Context, params: Params) -> dict[str, Any]:
    """Reconcile the shop's catalogue against the PIM. Returns the summary — an
    incomplete pass is reported through the return value, not by raising."""
    summary: dict[str, Any] = await catalog_sync.sync_catalog(
        ctx.resources["json_http"], ctx.resources["xml_http"]
    )
    return summary


async def doctor(ctx: Context) -> None:
    """Diagnose drift, then ask for a full reconcile and report what came back.

    A full idempotent pass is intentional even when the cheap existence check
    finds nothing: it also repairs mutable product fields, category and
    combination associations, empty image sets, attributes, and variants that no
    existence check can prove converged.
    """
    async with json_client() as json_http:
        reason = await _detect_drift(json_http)
    log.info("catalogue check (%s)", reason or "periodic full reconciliation")

    summary = await ctx.call(Topic.CATALOG_SYNC, ttl=SYNC_TTL)

    if summary["errors"]:
        log.warning("catalog sync incomplete: %s", summary["errors"])
    else:
        log.info("catalog sync complete")


# Registered imperatively so the doctor keeps its own kill-switch while living in
# the same service as the action it drives.
if configuration.get("catalog_doctor_enabled"):
    service.register_every(
        doctor,
        interval=configuration.get("catalog_doctor_interval"),
        id="catalog-doctor",
    )


async def _detect_drift(json_http: httpx.AsyncClient) -> str | None:
    """A short reason if the live catalogue differs from the PIM, else None.

    Compares Home's child categories (by name) and products (by reference), both
    read straight from the Webservice.
    """
    pim = load_pim()
    expected_categories = {c["name_en"] for c in pim["categories"] if c.get("active")}
    expected_references = {
        p.get("reference", "") for p in pim["products"] if p.get("active")
    }

    live_categories = {
        ps.lang_value(c.get("name"))
        for c in await ps.get_all(json_http, "categories")
        if str(c.get("id_parent")) == str(HOME_CATEGORY_ID)
        and str(c.get("active")) == "1"
    }
    # The sync is additive-only, so drift = something the PIM expects is MISSING
    # live (a subset check). Extra live items (e.g. leftover demo data) are not
    # the simulator's concern and must not keep re-triggering the sync.
    missing_categories = expected_categories - live_categories
    if missing_categories:
        return (
            f"{len(missing_categories)} category(ies) missing: "
            f"{sorted(missing_categories)}"
        )

    live_references = {
        p.get("reference", "") for p in await ps.get_all(json_http, "products")
    }
    missing_references = expected_references - live_references
    if missing_references:
        return f"{len(missing_references)} product(s) missing: {sorted(missing_references)}"

    return None
