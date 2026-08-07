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

# Orders accepted per pass. Each acceptance is a write that also triggers
# PrestaShop's own state-change side effects, so this drains in bounded batches
# rather than in one tick that runs for minutes.
#
# Raised from 25 after the public deployment showed what "the backlog is
# unbounded (hundreds)" is worth as an estimate: it was **50 223**, because the
# listing this bound applies to had no bound of its own and timed out on every
# pass since the shop opened. At 25 per five minutes the drain ran slower than
# orders arrived for the first hour of every day.
#
# 500 is a rate, not a capacity: 6 000/hour against ~126 orders/hour arriving.
# The one-off `scripts/settle_backlog.py` exists for the case this is still too
# slow for — an accumulated backlog you want gone now rather than by Thursday.
MAX_PER_PASS = 500


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
    """The next batch to settle — **bounded**, because the caller only ever uses
    that many.

    The `limit` is not an optimisation. Without it this asked the shop for every
    order in the awaiting state, and the caller then sliced the first
    `MAX_PER_PASS` off the result and discarded the rest. That is harmless while
    the backlog is the "hundreds" the note above imagines, and fatal past a
    certain size: on the public deployment the awaiting set reached 50 223 rows,
    PrestaShop could not serialise them inside the client's read timeout, and the
    call raised `httpx.ReadTimeout` before a single order was settled.

    The failure feeds itself, which is why it never recovered on its own. Every
    timed-out pass leaves the whole backlog in place and the arriving orders add
    to it, so each pass asks for a larger response than the one that just timed
    out. It had never once succeeded.
    """
    r = await json_http.get(
        "/orders",
        params={
            "filter[current_state]": AWAITING_BANK_WIRE,
            "display": "[id]",
            "limit": MAX_PER_PASS,
        },
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
