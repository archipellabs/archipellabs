"""Accept the bank-wire payments the shop is waiting on.

The storefront takes bank wire only, so every order lands in *Awaiting bank wire
payment* and stays there: nothing in the simulation ever reconciles a bank
statement. Orders therefore never reach a paid state, and every downstream signal
that depends on one — revenue, invoices, anything a report would count — stays
empty while the shop looks busy.

This stands in for the back-office clerk who checks the account each morning and
marks the transfers that arrived. It is deliberately credulous: every waiting
order is accepted, because there is no bank to disagree with. A payment flow that
can *refuse* is a different, later thing — it needs a notion of a transfer that
did not turn up, which is a business rule rather than a workaround.

Reuses the catalog's Webservice helpers/clients (one source of truth for the PS
plumbing), like the stock flow.
"""

import logging
from typing import Any

import httpx

from src.internal_flows.catalog import prestashop as ps

log = logging.getLogger("simulator.payments")

# ps_order_state ids, stable across a PrestaShop install.
AWAITING_BANK_WIRE = 10
PAYMENT_ACCEPTED = 2

# Orders accepted per pass. The backlog on a shop that has been running without
# this flow is unbounded (hundreds), and each acceptance is a write that also
# triggers PrestaShop's own state-change side effects — so drain it in bounded
# batches rather than in one tick that runs for minutes.
MAX_PER_PASS = 25


async def accept_bank_wire_payments(
    json_http: httpx.AsyncClient, xml_http: httpx.AsyncClient
) -> dict[str, Any]:
    """Move orders awaiting a bank wire to *Payment accepted*.

    Idempotent by construction: it only ever selects orders currently in the
    awaiting state, so a second pass over the same orders finds nothing.
    """
    waiting = await _orders_awaiting_bank_wire(json_http)
    accepted: list[int] = []
    errors: list[dict[str, str]] = []

    for order_id in waiting[:MAX_PER_PASS]:
        try:
            await _mark_paid(xml_http, order_id)
        except httpx.HTTPStatusError as exc:
            errors.append(
                {"order": str(order_id), "reason": str(exc.response.status_code)}
            )
            continue
        accepted.append(order_id)

    return {"waiting": len(waiting), "accepted": accepted, "errors": errors}


async def _orders_awaiting_bank_wire(json_http: httpx.AsyncClient) -> list[int]:
    r = await json_http.get(
        "/orders",
        params={"filter[current_state]": AWAITING_BANK_WIRE, "display": "[id]"},
    )
    r.raise_for_status()
    data = r.json()
    # PrestaShop returns a bare [] for an empty result and {"orders": [...]}
    # otherwise — the shape changes with the count, so both are handled.
    if isinstance(data, list):
        return []
    return [int(o["id"]) for o in data.get("orders", [])]


async def _mark_paid(xml_http: httpx.AsyncClient, order_id: int) -> None:
    """Add an order_history row, which is what actually moves an order's state.

    PUTting `current_state` on the order would change the field and skip
    everything PrestaShop hangs off the transition — invoice, stock, history.
    """
    body = ps.wrap(
        "order_history",
        ps.field("id_order", order_id),
        ps.field("id_order_state", PAYMENT_ACCEPTED),
    )
    await ps.post(xml_http, "order_histories", body)
