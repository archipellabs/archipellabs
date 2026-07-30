"""End-to-end customer-journey tests against a live PrestaShop (marker: e2e).

Requires a running PrestaShop reachable at SHOP_BASE_URL (default
`https://shop.archipellabs.test`). Skip the whole module by deselecting the `e2e`
marker:

    uv run pytest -m "not e2e"

Override via env vars:

    SHOP_BASE_URL=https://staging.example.com uv run pytest
    DEBUG_SHOW_BROWSER=true uv run pytest   # watch the browser
    FAST=false   uv run pytest              # keep realistic think-time pauses
"""

import os

import pytest

from src.external_flows.customer_arrivals.persona import generate_customer_profile
from src.external_flows.customer_journey.journey import run_customer_journey
from src.services.browser.service import browser_session

pytestmark = pytest.mark.e2e


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


BASE_URL = os.getenv("SHOP_BASE_URL", "https://shop.archipellabs.test")
SHOW_BROWSER = _env_bool("DEBUG_SHOW_BROWSER", False)
FAST = _env_bool("FAST", True)


def _completed_state_keys(result: dict) -> set[str]:
    return {e["state"] for e in result["events"] if e["event"] == "state_completed"}


def _event(result: dict, name: str, **match) -> dict:
    """The first emitted event with this name, and optionally these field values."""
    for event in result["events"]:
        if event["event"] == name and all(event.get(k) == v for k, v in match.items()):
            return event
    raise AssertionError(f"no {name} event matching {match}")


# How many delivery options each market is offered at checkout. The shop runs a
# domestic carrier and a cross-border one, so a US customer sees both and a
# Canadian sees only the second.
CARRIERS_OFFERED = {"US": 2, "CA": 1}


@pytest.mark.parametrize("country", ["US", "CA"])
async def test_guest_checkout_creates_order(country):
    """Once per market the shop sells to.

    Every market brings its own address validation (zip format, province list)
    and its own carrier coverage, and a market the shop cannot actually serve
    fails silently — the form simply never advances, which is indistinguishable
    from a customer changing their mind.
    """
    guest = generate_customer_profile(country=country)

    async with browser_session(headless=not SHOW_BROWSER) as ctx:
        result = await run_customer_journey(
            ctx,
            BASE_URL,
            journey="guest_checkout",
            guest=guest,
            fast=FAST,
        )

    assert result["success"], f"Journey failed: {result.get('error')}"

    # The address the customer actually typed, not just "the form advanced".
    # Falling back to the first option in a dropdown also advances the form, and
    # would put every customer in the same region without failing anything.
    address = _event(result, "checkout_step_completed", step="address")
    assert (address["country"], address["city"], address["postcode"]) == (
        guest.country,
        guest.city,
        guest.postcode,
    )
    assert _event(result, "checkout_state_selected")["state"] == guest.state

    # Coverage differs per market, and a market losing its carrier looks exactly
    # like a customer changing their mind unless this number is watched.
    shipping = _event(result, "checkout_shipping_options")
    assert shipping["count"] == CARRIERS_OFFERED[country], (
        f"{country} was offered {shipping['count']} carrier(s)"
    )
    assert result["completed"] is True
    assert result["abandoned"] is False
    assert result["final_url"].startswith(f"{BASE_URL}/order-confirmation"), result[
        "final_url"
    ]
    assert "id_order=" in result["final_url"]

    assert _completed_state_keys(result) >= {
        "landing",
        "category",
        "catalog",
        "product",
        "add_to_cart",
        "proceed_to_checkout",
        "cart",
        "checkout_personal",
        "checkout_address",
        "checkout_shipping",
        "checkout_payment",
        "confirmation",
    }


async def test_add_to_cart_abandon_emits_session_abandoned():
    async with browser_session(headless=not SHOW_BROWSER) as ctx:
        result = await run_customer_journey(
            ctx,
            BASE_URL,
            journey="add_to_cart_abandon",
            guest=generate_customer_profile(country="US"),
            fast=FAST,
        )

    assert result["success"], f"Journey failed: {result.get('error')}"
    assert result["abandoned"] is True
    assert result["completed"] is False
    assert result["abandoned_from"] == "continue_shopping"

    event_names = [e["event"] for e in result["events"]]
    assert "add_to_cart" in event_names
    assert "continue_shopping" in event_names
    assert "session_abandoned" in event_names

    # We left while still on the product page.
    assert result["final_url"], "final_url should be captured on abandon"


async def test_multi_item_checkout_creates_order_with_two_items():
    async with browser_session(headless=not SHOW_BROWSER) as ctx:
        result = await run_customer_journey(
            ctx,
            BASE_URL,
            journey="multi_item_checkout",
            guest=generate_customer_profile(country="US"),
            fast=FAST,
        )

    assert result["success"], f"Journey failed: {result.get('error')}"
    assert result["completed"] is True
    assert result["abandoned"] is False
    assert result["final_url"].startswith(f"{BASE_URL}/order-confirmation"), result[
        "final_url"
    ]

    # Two add_to_cart events — one per pass through the "Continue shopping" loop.
    add_to_cart_events = [e for e in result["events"] if e["event"] == "add_to_cart"]
    assert len(add_to_cart_events) == 2

    # Cart count from the modal after the second addition should be 2.
    assert result["cart_count"] == 2

    assert _completed_state_keys(result) >= {
        "landing",
        "category_1",
        "catalog_1",
        "product_1",
        "add_to_cart_1",
        "continue_shopping",
        "category_2",
        "catalog_2",
        "product_2",
        "add_to_cart_2",
        "proceed_to_checkout",
        "cart",
        "confirmation",
    }
