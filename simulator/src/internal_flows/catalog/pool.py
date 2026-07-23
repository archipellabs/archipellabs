"""catalog — internal Pool with a single flow: sync the PrestaShop catalog.

The lifespan opens the two PrestaShop async clients once (JSON reads + XML writes)
and shares them across handler runs. `max_slots=1` serialises catalog operations
— they mutate the same shop and must not overlap. The flow delegates to the
`sync` logic, triggered on demand by emitting CATALOG_SYNC. The sync is purely
additive (it never deletes) — clearing install demo data is a setup-time concern
owned by provisioning, not the simulator. To run the sync directly against a live
shop, see `tests/integration/test_catalog.py`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from runtime import Config, Context, Event, Pool, Resources

from src.internal_flows.catalog import sync as catalog_sync
from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.topics import Topic


@asynccontextmanager
async def prestashop_lifespan(config: Config) -> AsyncIterator[Resources]:
    json_http = json_client()
    xml_http = xml_client()
    try:
        yield {"json_http": json_http, "xml_http": xml_http}
    finally:
        await json_http.aclose()
        await xml_http.aclose()


pool = Pool("catalog", max_slots=1, lifespan=prestashop_lifespan)


@pool.flow(consumes=Topic.CATALOG_SYNC)
async def sync(ctx: Context, event: Event) -> None:
    summary = await catalog_sync.sync_catalog(
        ctx.resources["json_http"], ctx.resources["xml_http"]
    )
    if summary["errors"]:
        # Returning normally acknowledges the event. Surface an incomplete pass so
        # it remains visibly failed; the periodic doctor will emit a fresh reconcile
        # event even on a runtime version that cannot reclaim pending messages yet.
        raise RuntimeError(f"catalog sync incomplete: {summary['errors']}")
