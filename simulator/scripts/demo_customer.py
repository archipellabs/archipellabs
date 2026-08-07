#!/usr/bin/env python3
"""One customer, one visible browser, narrated — for showing the lab to a room.

**The same journey the simulator runs**, not a demo copy of it. It calls
`run_customer_journey` with the same state graph, the same selectors and the same
think-time as the traffic already hitting the shop, so what an audience watches is
the thing under discussion rather than a re-enactment that can quietly drift from
it. The only differences are the ones a demo needs: the browser is visible, the
steps are slowed down enough to follow, and each event is narrated in the terminal
as it happens.

    ./demo_customer.sh                          a US customer on demo1
    ./demo_customer.sh --country CA             the market that had no carrier
    ./demo_customer.sh --url https://shop.archipellabs.test   the local stack

The run is tagged as simulated traffic on every request, the same way the pool
tags its own. A demo customer is not a real one, and the analytics should not have
to guess.
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from playwright.async_api import async_playwright

from src.external_flows.customer_arrivals.persona import generate_customer_profile
from src.external_flows.customer_journey.devices import context_kwargs
from src.external_flows.customer_journey.journey import run_customer_journey
from src.external_flows.customer_journey.pool import SIMULATOR_HEADER

PUBLIC = "https://store.demo1.archipellabs.com"


class Narrator(logging.Handler):
    """Renders the flow trace as sentences instead of JSON.

    The events already exist — `FlowTrace` logs one per step. This only decides how
    they read on a projector: one line per step, the noisy ones folded away.
    """

    QUIET = {"thinking", "state_entered"}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event: dict[str, Any] = json.loads(record.getMessage())
        except (json.JSONDecodeError, TypeError):
            return
        name = event.get("event", "")
        if name in self.QUIET:
            return
        print("   " + self.sentence(name, event), flush=True)

    def sentence(self, name: str, e: dict[str, Any]) -> str:
        """One line per event, using the fields the states actually emit.

        Written against `grep emit\\( states/*.py` rather than from memory: the
        first draft of this invented `added_to_cart` and `product_selected`, which
        exist nowhere. Both would have fallen through to the generic branch and
        printed a raw dict — legible, but wrong in front of a room.
        """
        if name == "session_started":
            who = e.get("guest") or {}
            return (
                f"→ {who.get('firstname', '?')} {who.get('lastname', '?')} "
                f"from {who.get('city', '?')}, {who.get('country', '?')}"
                f" · journey “{e.get('journey')}”"
            )
        if name == "page_viewed":
            return f"  lands on the {e.get('page')} page"
        if name == "activation_dismissed":
            return "  clears the shop's activation banner"
        if name == "activation_skipped":
            return "  (no activation banner)"
        if name == "product_viewed":
            return f"  reads the {e.get('product_name')} page"
        if name == "cart_modal_shown":
            n = e.get("cart_count")
            return f"  cart now holds {n} item{'' if n == 1 else 's'}"
        if name == "modal_proceed_clicked":
            return "  chooses to check out"
        if name == "continue_shopping":
            return "  goes back to browsing"
        if name == "checkout_state_selected":
            return f"  picks the state “{e.get('state')}”"
        if name == "checkout_state_unavailable":
            return "  ⚠ the address form offers no state for this country"
        if name == "category_clicked":
            return f"  browses “{e.get('category')}”"
        if name == "product_list_viewed":
            return "  scans the products"
        if name == "product_clicked":
            return f"  opens {e.get('product_name')}"
        if name == "add_to_cart":
            return f"  adds {e.get('product_name')} to the cart"
        if name == "cart_viewed":
            return "  opens the cart"
        if name == "checkout_started":
            return "  starts checkout"
        if name == "checkout_step_completed":
            return f"  checkout · {e.get('step')} done"
        if name == "checkout_shipping_options":
            offered = e.get("count")
            if offered == 0:
                return "  ⚠ no delivery option is offered for this address"
            return f"  {offered} delivery option(s) offered"
        if name == "payment_attempted":
            return f"  pays by {e.get('method')}"
        if name == "order_created":
            return f"✓ order placed — {e.get('order_reference')}"
        if name == "order_not_confirmed":
            return f"✗ no confirmation page — {e.get('url')}"
        if name == "session_abandoned":
            return f"· gives up at {e.get('from_state')}"
        if name == "state_completed":
            ms = e.get("duration_ms")
            took = f" ({ms} ms)" if ms is not None else ""
            return f"  ── {e.get('state')}{took}"
        if name == "session_finished":
            if e.get("completed"):
                return "✓ the order went through"
            if e.get("abandoned"):
                return "· the customer left without buying"
            return f"✗ {(e.get('error') or {}).get('message', 'failed')}"
        detail = {k: v for k, v in e.items() if k not in {"flow_id", "event", "at"}}
        return f"  {name}" + (f" {detail}" if detail else "")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=PUBLIC, help=f"shop to visit (default: {PUBLIC})")
    parser.add_argument("--country", default="US", help="market the customer comes from")
    parser.add_argument("--journey", default="guest_checkout")
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=300,
        help="milliseconds between Playwright actions, so a room can follow (0 = full speed)",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="leave the browser open at the end, to talk over the confirmation page",
    )
    args = parser.parse_args()

    logging.getLogger("flow").addHandler(Narrator())
    logging.getLogger("flow").setLevel(logging.INFO)
    logging.getLogger("flow").propagate = False

    guest = generate_customer_profile(country=args.country)

    print(f"\n  {args.url}  ·  {args.country}  ·  {args.journey}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=args.slow_mo)
        kwargs = context_kwargs(pw.devices, None)
        kwargs["extra_http_headers"] = {
            **SIMULATOR_HEADER,
            **kwargs.get("extra_http_headers", {}),
        }
        # A window worth projecting: the default 1280x720 crops the checkout.
        kwargs["viewport"] = {"width": 1440, "height": 900}
        context = await browser.new_context(**kwargs)
        try:
            summary = await run_customer_journey(
                context, args.url, guest=guest, journey=args.journey
            )
        finally:
            if args.keep_open:
                print("\n  (browser left open — press Enter to close)")
                await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
            await context.close()
            await browser.close()

    print()
    if summary["completed"]:
        # Both identifiers, because they answer different questions: the reference
        # is what the customer quotes on their bank transfer, the id is what you
        # type into the back office.
        order_id = ""
        for part in (summary["final_url"] or "").split("?")[-1].split("&"):
            if part.startswith("id_order="):
                order_id = part.removeprefix("id_order=")
        print(
            f"  order {summary['order_reference'] or '?'} "
            f"(#{order_id or '?'}) · {summary['final_url']}"
        )
        return 0
    if summary["abandoned"]:
        print(f"  abandoned at {summary['abandoned_from']}")
        return 0
    print(f"  failed: {summary['error']}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
