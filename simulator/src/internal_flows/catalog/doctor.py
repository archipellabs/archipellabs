"""catalog doctor — producer (Scheduler) that periodically reconciles the catalogue.

Reads the live catalogue through the Webservice API (robust, decoupled from the
storefront), records a concise missing-resource diagnosis, then emits CATALOG_SYNC
on every tick. A full idempotent pass is intentional: it also repairs mutable
product fields, category/combination associations, empty image sets, attributes,
and variants that a cheap existence check cannot prove converged. The catalog pool
runs with max_slots=1, so duplicate emits are processed serially.
"""

import logging

import httpx
from runtime import Context, Scheduler

from src.config import settings
from src.internal_flows.catalog import prestashop as ps
from src.internal_flows.catalog.client import json_client
from src.internal_flows.catalog.sync import HOME_CATEGORY_ID, load_pim
from src.internal_flows.topics import Topic

log = logging.getLogger("simulator.catalog.doctor")

scheduler = Scheduler("catalog-doctor")


@scheduler.every(settings.catalog_doctor_interval)
async def tick(ctx: Context) -> None:
    async with json_client() as json_http:
        reason = await _detect_drift(json_http)
    diagnosis = reason or "periodic full reconciliation"
    log.info("catalogue check (%s) → emitting %s", diagnosis, Topic.CATALOG_SYNC)
    await ctx.emit(Topic.CATALOG_SYNC)


async def _detect_drift(json_http: httpx.AsyncClient) -> str | None:
    """A short reason if the live catalogue differs from the PIM, else None.

    Compares Home's child categories (by name) and products (by reference),
    both read straight from the Webservice.
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
        return f"{len(missing_categories)} category(ies) missing: {sorted(missing_categories)}"

    live_references = {
        p.get("reference", "") for p in await ps.get_all(json_http, "products")
    }
    missing_references = expected_references - live_references
    if missing_references:
        return f"{len(missing_references)} product(s) missing: {sorted(missing_references)}"

    return None
