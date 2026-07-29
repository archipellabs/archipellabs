"""Scenario: a carrier stops serving Canada, and nobody says so.

The reference incident from doc/agent-org-lab.md §2, driven end to end through
the real chain: master data → integration layer → storefront → customer.

One line disappears from `carriers.csv`. Nothing errors. Every service stays up,
every health check stays green, the US keeps selling — and Canadian customers
reach the shipping step, are offered nothing, and leave. That is the whole point:
the failure is invisible at the infrastructure layer and only exists as a
business outcome, which is why the assertions here are about whether a customer
could buy rather than about any status code.

Slow by nature: several real browser journeys, plus waiting for the integration
layer to reconcile. Run with `-m scenario`.
"""

import os

import pytest

from src.external_flows.customer_arrivals.persona import generate_customer_profile
from src.external_flows.customer_journey.journey import run_customer_journey
from src.services.browser.service import browser_session
from tests.scenarios.conftest import delivery_rows, until_serving, zone_of

pytestmark = [pytest.mark.scenario, pytest.mark.e2e]

BASE_URL = os.getenv("SHOP_BASE_URL", "https://localhost")
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() in {"1", "true", "yes"}
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
    async with browser_session(headless=HEADLESS) as ctx:
        return await run_customer_journey(
            ctx,
            BASE_URL,
            journey="guest_checkout",
            guest=generate_customer_profile(country=country),
            fast=FAST,
        )


def reached(result: dict) -> set[str]:
    return {e["state"] for e in result["events"] if e["event"] == "state_completed"}


async def test_withdrawing_canada_from_the_feed_stops_canadian_checkout(
    master_data, shop
):
    canada = await zone_of(shop, "CA")
    united_states = await zone_of(shop, "US")

    # ── the company is healthy ───────────────────────────────────────────────
    await until_serving(shop, CROSS_BORDER, {united_states, canada})
    before = await delivery_rows(shop, CROSS_BORDER)

    # ── one line disappears from the master data ─────────────────────────────
    master_data("carriers.csv", WITHOUT_CANADA)

    # Canada gone AND the US kept, as one settled state. The US half is not a
    # formality: it is what makes the two markets independently observable, and
    # what a single carrier could never have shown.
    await until_serving(shop, CROSS_BORDER, {united_states})

    # And the US row is the SAME row, not a replacement. The sync merges — it
    # touches only what the feed changed — so withdrawing Canada never takes the
    # US offline, not even for the moment it takes to rebuild. A rebuild would
    # satisfy the assertion above and still have dropped every US order placed
    # while it ran.
    after = await delivery_rows(shop, CROSS_BORDER)
    assert after[united_states] == before[united_states], (
        "withdrawing Canada replaced the US delivery row instead of leaving it "
        "alone — the sync is rebuilding, not merging"
    )

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


async def test_the_shop_recovers_when_the_line_is_restored(
    master_data, shop, read_feed
):
    """The other half: an incident you cannot undo is a migration, not an incident.

    Separate test so the recovery path is exercised on its own — if restoring the
    feed did not heal the shop, the previous test would still pass and leave the
    company broken for everything after it.
    """
    canada = await zone_of(shop, "CA")
    united_states = await zone_of(shop, "US")
    original = read_feed("carriers.csv")

    master_data("carriers.csv", WITHOUT_CANADA)
    await until_serving(shop, CROSS_BORDER, {united_states})

    master_data("carriers.csv", original)
    await until_serving(shop, CROSS_BORDER, {united_states, canada})

    canadian = await buys("CA")
    assert canadian["completed"] is True, (
        "restoring the feed should restore Canadian checkout"
    )
