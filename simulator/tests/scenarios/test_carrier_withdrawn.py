"""Scenario: a carrier stops serving Canada, and nobody says so.

The lab's reference incident, driven end to end through
the real chain: master data → integration layer → storefront → customer.

One line disappears from `carriers.csv`. Nothing errors. Every service stays up,
every health check stays green, the US keeps selling — and Canadian customers
reach the shipping step, are offered nothing, and leave. That is the whole point:
the failure is invisible at the infrastructure layer and only exists as a
business outcome, which is why the assertions here are about whether a customer
could buy rather than about any status code.

The scenario runs the full arc — break, observe, fix, confirm the fix — and ends
with the company healthy and *verified* healthy. An incident you cannot undo is a
migration, not an incident; and a scenario that leaves the shop dark for whatever
runs next is worse than one that fails.

Slow by nature: three real browser journeys, plus waiting for the integration
layer to reconcile between each step. Run with `-m scenario`.
"""

import os

import pytest

from src.external_flows.customer_arrivals.persona import generate_customer_profile
from src.external_flows.customer_journey.journey import run_customer_journey
from src.services.browser.service import browser_session
from tests.scenarios.conftest import delivery_rows, until_serving, zone_of

pytestmark = [pytest.mark.scenario, pytest.mark.e2e]

BASE_URL = os.getenv("SHOP_BASE_URL", "https://shop.archipellabs.test")
SHOW_BROWSER = os.getenv("DEBUG_SHOW_BROWSER", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
FAST = os.getenv("FAST", "true").strip().lower() in {"1", "true", "yes"}

CROSS_BORDER = "TimberWorks Cross-Border"

# carriers.csv with the Canadian line removed — the whole incident.
WITHOUT_CANADA = """\
carrier_id,carrier_code,carrier_name,active,country,price,delay_days
8f3a1c56-2d41-4b90-9e77-1a2b3c4d5e6f,GROUND,TimberWorks Ground,1,US,5.00,3
b7e2d904-5c18-4a3f-8d61-9f0e1a2b3c4d,XBORDER,TimberWorks Cross-Border,1,US,5.00,5
"""


async def buys(country: str) -> dict:
    """Send one customer from `country` through checkout and report what happened."""
    async with browser_session(headless=not SHOW_BROWSER) as ctx:
        return await run_customer_journey(
            ctx,
            BASE_URL,
            journey="guest_checkout",
            guest=generate_customer_profile(country=country),
            fast=FAST,
        )


def reached(result: dict) -> set[str]:
    return {e["state"] for e in result["events"] if e["event"] == "state_completed"}


async def test_canada_goes_dark_and_is_brought_back(master_data, shop, read_feed):
    canada = await zone_of(shop, "CA")
    united_states = await zone_of(shop, "US")
    original = read_feed("carriers.csv")

    # ── the company is healthy ───────────────────────────────────────────────
    await until_serving(shop, CROSS_BORDER, {united_states, canada})
    before = await delivery_rows(shop, CROSS_BORDER)

    # ── one line disappears from the master data ─────────────────────────────
    master_data("carriers.csv", WITHOUT_CANADA)

    # Canada gone AND the US kept, as one settled state. The US half is not a
    # formality: it is what makes the two markets independently observable, and
    # what a single carrier could never have shown.
    await until_serving(shop, CROSS_BORDER, {united_states})

    # ── the only symptom is a customer who cannot buy ────────────────────────
    canadian = await buys("CA")
    assert canadian["completed"] is False, "a Canadian should not be able to check out"
    assert "checkout_address" in reached(canadian), (
        "the Canadian should get as far as entering an address — the failure is at "
        "shipping, not before it"
    )
    assert "checkout_shipping" not in reached(canadian)

    american = await buys("US")
    assert american["completed"] is True, "the US market must keep selling throughout"

    # ── the fix: put the line back ───────────────────────────────────────────
    # Asserted here rather than left to the fixture's restore, so that a scenario
    # which cannot be undone fails loudly instead of quietly handing the next
    # test a shop that still cannot ship to Canada.
    master_data("carriers.csv", original)
    await until_serving(shop, CROSS_BORDER, {united_states, canada})

    healed = await buys("CA")
    assert healed["completed"] is True, (
        "restoring the line to carriers.csv should restore Canadian checkout"
    )

    # Through the whole break-and-fix cycle the US delivery row was never
    # replaced. That is the merge (doc §6): only the row the feed changed is
    # touched, so the shop is never briefly unable to ship anywhere — which a
    # wipe-and-rebuild sync would have done twice over, and which none of the
    # assertions above would have caught.
    after = await delivery_rows(shop, CROSS_BORDER)
    assert after[united_states] == before[united_states], (
        "the US delivery row was replaced — the sync is rebuilding, not merging"
    )
