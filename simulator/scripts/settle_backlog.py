#!/usr/bin/env python3
"""Settle every waiting bank wire at once, through the Webservice API.

The scheduled flow (`internal_flows/payments`) settles `MAX_PER_PASS` every five
minutes, which is the right shape for keeping up and the wrong one for catching
up. This is the catch-up: one pass, the whole backlog, bounded concurrency.

**Through the API, deliberately.** Moving `ps_orders.current_state` with SQL
would be minutes rather than an hour, and would produce a shop that lies: the
label reads *Payment accepted* while `total_paid_real` stays at 0, no invoice
exists, and `ps_order_history` has no row to explain the transition. Revenue —
the thing the backlog was hiding — would still be zero, and the next person to
look would have a harder question than the one they started with. Posting an
`order_history` is what PrestaShop hangs all of that off, so this posts one per
order and lets the shop do its own work.

    docker exec -it simulator python scripts/settle_backlog.py --dry-run
    docker exec -it simulator python scripts/settle_backlog.py

Reads the same environment the simulator does, so it needs no arguments and
cannot point at a different shop by accident.
"""

import argparse
import asyncio
import os
import sys
import time
from typing import Any

import httpx

from src.internal_flows.catalog import prestashop as ps
from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.payments.accept import AWAITING_BANK_WIRE, PAYMENT_ACCEPTED

PAGE = 500
"""Ids per listing request.

Bounded because the unbounded version is what broke the scheduled flow: asking
for 50 223 orders in one response timed out before PrestaShop finished
serialising it. Ids only (`display=[id]`), so a page is small."""

CONCURRENCY = int(os.environ.get("SETTLE_CONCURRENCY", "8"))
"""Simultaneous writes. Override with `SETTLE_CONCURRENCY`.

Each one makes PrestaShop generate an invoice and move stock while the simulator
is still driving real browser traffic against the same shop, so this trades the
drain against the storefront a visitor is looking at.

**The limit is the database, not the network.** At eight the measured rate was
5.6/s — about 1.4s per write — with `prestashopdb` already burning 2.3 cores of
the host's 8 and `prestashop` another 1.3. Raising this helps only while the
database has headroom; past that it queues, the rate stops improving and the
storefront starts waiting behind the backlog. Watch `docker stats` and the
storefront's response time when you change it, rather than assuming a bigger
number is faster."""


async def waiting_ids(http: httpx.AsyncClient) -> list[int]:
    """Every order awaiting a wire, oldest first, paginated.

    **No `sort`, deliberately.** `sort=[id_ASC]` — which the catalog's own
    paginator passes, and which works there — returns an empty list when combined
    with `filter[current_state]` on this resource. Not an error, not a 400: a
    `200 OK` carrying `[]`, which reads exactly like a shop with no unpaid orders.
    The first version of this script reported "0 order(s) awaiting a bank wire"
    against a shop holding 49 699 of them.

    Rows come back id-ascending without it, which is the order this wants anyway.
    """
    found: list[int] = []
    offset = 0
    while True:
        r = await http.get(
            "/orders",
            params={
                "filter[current_state]": AWAITING_BANK_WIRE,
                "display": "[id]",
                "limit": f"{offset},{PAGE}",
            },
        )
        r.raise_for_status()
        data: Any = r.json()
        # PrestaShop answers a bare [] for an empty result and {"orders": [...]}
        # otherwise — the shape changes with the count.
        rows = [] if isinstance(data, list) else data.get("orders", [])
        if not rows:
            return found
        found.extend(int(o["id"]) for o in rows)
        offset += PAGE
        print(f"  listed {len(found)}…", flush=True)


async def settle(
    http: httpx.AsyncClient, order_id: int, gate: asyncio.Semaphore
) -> str | None:
    """Post the history row that moves one order. Returns an error, or None."""
    async with gate:
        body = ps.wrap(
            "order_history",
            ps.field("id_order", order_id),
            ps.field("id_order_state", PAYMENT_ACCEPTED),
        )
        try:
            await ps.post(http, "order_histories", body)
        except httpx.HTTPStatusError as exc:
            return f"order {order_id}: HTTP {exc.response.status_code}"
        except httpx.HTTPError as exc:
            return f"order {order_id}: {type(exc).__name__}"
        return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count the backlog and change nothing",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="settle at most this many (0 = all). Use a small number first.",
    )
    args = parser.parse_args()

    async with json_client() as read:
        print("listing the backlog…", flush=True)
        ids = await waiting_ids(read)

    if args.limit:
        ids = ids[: args.limit]

    print(f"\n{len(ids)} order(s) awaiting a bank wire.")
    if not ids:
        return 0
    if args.dry_run:
        print("dry run — nothing written.")
        return 0

    gate = asyncio.Semaphore(CONCURRENCY)
    started = time.monotonic()
    errors: list[str] = []
    done = 0

    async with xml_client() as write:
        tasks = [asyncio.create_task(settle(write, i, gate)) for i in ids]
        for task in asyncio.as_completed(tasks):
            problem = await task
            done += 1
            if problem:
                errors.append(problem)
            if done % 250 == 0 or done == len(ids):
                rate = done / max(time.monotonic() - started, 1e-9)
                left = (len(ids) - done) / rate if rate else 0
                print(
                    f"  {done}/{len(ids)}  {rate:.1f}/s  "
                    f"~{left / 60:.0f} min left  {len(errors)} error(s)",
                    flush=True,
                )

    print(f"\nsettled {done - len(errors)} of {len(ids)}.")
    for problem in errors[:20]:
        print(f"  {problem}")
    if len(errors) > 20:
        print(f"  … and {len(errors) - 20} more")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
