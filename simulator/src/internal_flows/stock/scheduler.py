"""stock — a producer-only service that keeps tracked products topped up.

A standalone business flow: every `stock_check_interval` it checks the tracked
products' stock and refills any that have dipped below the floor. It does the work
in the tick (no message) — a small, self-contained reconciliation loop, so this
service consumes nothing and therefore needs no `max_slots`.
"""

import logging

from runtime import Context, Service

from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.stock.refill import refill_stock
from src.services.configuration.service import configuration

log = logging.getLogger("simulator.stock")

service = Service("stock-refill")


@service.every(configuration.get("stock_check_interval"))
async def tick(ctx: Context) -> None:
    async with json_client() as json_http, xml_client() as xml_http:
        summary = await refill_stock(json_http, xml_http)

    if summary["refilled"]:
        log.info("stock refilled: %s", summary["refilled"])
    for err in summary["errors"]:
        log.warning("stock issue: %s", err)
