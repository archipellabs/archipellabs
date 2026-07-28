"""payments — a producer-only service that settles the shop's bank wires.

Like the stock flow: a small, self-contained reconciliation loop that does its
work in the tick (no message), so it consumes nothing and needs no `max_slots`.
"""

import logging

from runtime import Context, Service

from src.config import settings
from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.payments.accept import accept_bank_wire_payments

log = logging.getLogger("simulator.payments")

service = Service("payment-settlement")


@service.every(settings.payment_check_interval)
async def tick(ctx: Context) -> None:
    async with json_client() as json_http, xml_client() as xml_http:
        summary = await accept_bank_wire_payments(json_http, xml_http)

    if summary["accepted"]:
        log.info(
            "accepted %d bank wire(s), %d still waiting",
            len(summary["accepted"]),
            summary["waiting"] - len(summary["accepted"]),
        )
    for err in summary["errors"]:
        log.warning("payment issue: %s", err)
