"""Fast selector-health check for the customer-journey storefront selectors.

The full journey test (`test_customer_journey.py`) is the deep, end-to-end check —
but when a PrestaShop/theme bump breaks selectors it times out 30s deep in the
flow at the *first* dead selector and stops, so you rediscover them one slow run
at a time. This is the cheap first line of defence instead: it walks the
storefront / cart / checkout-entry surface with short timeouts and **collects
every failure in one short run**, tagged with the state each selector belongs to.

Design:
- It imports the selector constants straight from the journey `states/*`, so it
  tests *exactly* what the journey uses — one source of truth, no copies to drift.
- It navigates by URL / link-iteration rather than by the selectors under test, so
  a single broken selector doesn't blind every check downstream of it.

Scope: landing top-menu, catalog grid, product page, add-to-cart modal, and the
checkout *entry* (cart + personal-information landmarks). The deeper checkout
steps (address/shipping/payment) need valid form submissions to reach and stay
covered by the full journey test.

    uv run pytest tests/integration/test_prestashop_selectors.py -s

Requires a live shop with a populated catalog (same prerequisites as the other
integration tests). Defaults to headless; override with HEADLESS=false.
"""

import os

import pytest
from playwright.async_api import Page

from src.external_flows.customer_journey.states.add_to_cart import (
    ADD_TO_CART_BUTTON,
    CART_MODAL_PRODUCT_COUNT,
)
from src.external_flows.customer_journey.states.cart import PROCEED_TO_CHECKOUT_BUTTON
from src.external_flows.customer_journey.states.catalog import (
    PRODUCT_MINIATURE,
    PRODUCT_OUT_OF_STOCK_FLAG,
    PRODUCT_TITLE_LINK,
)
from src.external_flows.customer_journey.states.category import CATEGORY_LINK
from src.external_flows.customer_journey.states.checkout_personal import (
    FIELD_EMAIL,
    FIELD_FIRSTNAME,
    FIELD_LASTNAME,
    PERSONAL_SECTION,
    REQUIRED_CHECKBOXES,
    SUBMIT,
)
from src.external_flows.customer_journey.states.continue_shopping import CONTINUE_BUTTON
from src.external_flows.customer_journey.states.landing import ACTIVATION_LOGO_LINK
from src.external_flows.customer_journey.states.proceed_to_checkout import PROCEED_LINK
from src.external_flows.customer_journey.states.selectors import CART_MODAL
from src.services.browser.service import browser_session

pytestmark = pytest.mark.integration

BASE_URL = os.getenv("SHOP_BASE_URL", "https://localhost")
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() in {"1", "true", "yes"}
CHECK_TIMEOUT_MS = 3_000
GOTO_TIMEOUT_MS = 12_000


class Report:
    """Collects per-selector results so one run surfaces every failure at once."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []  # state, name, status, detail

    async def check(
        self,
        state: str,
        name: str,
        page: Page,
        selector: str,
        *,
        present_only: bool = False,
    ) -> bool:
        loc = page.locator(selector)
        wanted = "attached" if present_only else "visible"
        try:
            await loc.first.wait_for(state=wanted, timeout=CHECK_TIMEOUT_MS)
            self.rows.append((state, name, "ok", f"count={await loc.count()}"))
            return True
        except Exception as exc:
            self.rows.append((state, name, "FAIL", type(exc).__name__))
            return False

    def info(self, state: str, name: str, detail: str) -> None:
        self.rows.append((state, name, "info", detail))

    def blocked(self, state: str, name: str, reason: str) -> None:
        self.rows.append((state, name, "blocked", reason))

    @property
    def failures(self) -> list[tuple[str, str, str, str]]:
        return [r for r in self.rows if r[2] == "FAIL"]

    def render(self) -> str:
        sw = max((len(r[0]) for r in self.rows), default=5)
        nw = max((len(r[1]) for r in self.rows), default=5)
        return "\n".join(
            f"  {state:<{sw}}  {status:<7}  {name:<{nw}}  {detail}"
            for state, name, status, detail in self.rows
        )


async def _dismiss_activation(page: Page) -> None:
    """The shop may show an activation/landing page; click the logo to enter."""
    logo = page.locator(ACTIVATION_LOGO_LINK).first
    try:
        await logo.wait_for(state="visible", timeout=2_000)
        await logo.click()
        await page.wait_for_load_state("domcontentloaded", timeout=GOTO_TIMEOUT_MS)
    except Exception:
        pass


async def _find_shoppable_category(page: Page) -> tuple[str | None, str | None]:
    """First top-menu category that has an in-stock product, as
    (category_url, product_url). Picking by live stock (rather than a fixed
    category) keeps the add-to-cart path exercisable as stock shifts, and leaves
    `page` on the chosen category so the grid checks run there."""
    links = page.locator(CATEGORY_LINK)
    hrefs = [
        href
        for i in range(await links.count())
        if (href := await links.nth(i).get_attribute("href"))
    ]
    for href in hrefs:
        await page.goto(href, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        product_url = await _first_in_stock_product_url(page)
        if product_url:
            return href, product_url
    return None, None


async def _first_in_stock_product_url(page: Page) -> str | None:
    minis = page.locator(PRODUCT_MINIATURE)
    for i in range(await minis.count()):
        tile = minis.nth(i)
        if await tile.locator(PRODUCT_OUT_OF_STOCK_FLAG).count() == 0:
            href = await tile.locator(PRODUCT_TITLE_LINK).first.get_attribute("href")
            if href:
                return href
    return None


async def _report_out_of_stock(page: Page, report: Report) -> None:
    """The out-of-stock flag is conditional (rendered only on sold-out tiles), so
    we can't assert presence. Record flagged/total instead — a human reading the
    report can spot `flagged=0` when stock-outs are expected (a silent class
    rename), without the check false-failing when every product is in stock."""
    total = await page.locator(PRODUCT_MINIATURE).count()
    flagged = (
        await page.locator(PRODUCT_MINIATURE)
        .filter(has=page.locator(PRODUCT_OUT_OF_STOCK_FLAG))
        .count()
    )
    report.info("catalog", "out_of_stock_flag", f"flagged={flagged}/total={total}")


async def _run(page: Page, report: Report) -> None:
    # --- landing / top-menu ---
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
    await _dismiss_activation(page)
    if not await report.check("category", "category_link", page, CATEGORY_LINK):
        report.blocked("catalog+", "*", "top-menu category link not found")
        return

    category_url, product_url = await _find_shoppable_category(page)
    if category_url is None or product_url is None:
        report.blocked("catalog+", "*", "no category with an in-stock product")
        return

    # --- catalog grid (we are on the shoppable category) ---
    await report.check("catalog", "product_miniature", page, PRODUCT_MINIATURE)
    await report.check(
        "catalog",
        "product_title_link",
        page,
        f"{PRODUCT_MINIATURE} {PRODUCT_TITLE_LINK}",
    )
    await _report_out_of_stock(page, report)

    # product_url is guaranteed in-stock by the finder above.
    await page.goto(product_url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)

    # --- product page ---
    if not await report.check(
        "product", "add_to_cart_button", page, ADD_TO_CART_BUTTON
    ):
        report.blocked("modal+", "*", "add-to-cart button missing")
        return
    await page.locator(ADD_TO_CART_BUTTON).first.click()

    # --- add-to-cart modal ---
    await report.check("add_to_cart", "cart_modal", page, CART_MODAL)
    await report.check("add_to_cart", "cart_count_line", page, CART_MODAL_PRODUCT_COUNT)
    await report.check("continue_shopping", "continue_button", page, CONTINUE_BUTTON)
    await report.check("proceed_to_checkout", "proceed_link", page, PROCEED_LINK)

    # --- cart page (URL nav: the cart persists, so we decouple from the modal
    #     proceed link and still reach the cart's own proceed button) ---
    await page.goto(
        f"{BASE_URL}/cart?action=show",
        wait_until="domcontentloaded",
        timeout=GOTO_TIMEOUT_MS,
    )
    await report.check(
        "cart", "proceed_to_checkout_button", page, PROCEED_TO_CHECKOUT_BUTTON
    )

    # --- checkout entry (personal-information landmarks; URL nav to /order) ---
    await page.goto(
        f"{BASE_URL}/order", wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS
    )
    await report.check("checkout_personal", "personal_section", page, PERSONAL_SECTION)
    await report.check("checkout_personal", "field_firstname", page, FIELD_FIRSTNAME)
    await report.check("checkout_personal", "field_lastname", page, FIELD_LASTNAME)
    await report.check("checkout_personal", "field_email", page, FIELD_EMAIL)
    await report.check(
        "checkout_personal",
        "required_checkboxes",
        page,
        REQUIRED_CHECKBOXES,
        present_only=True,
    )
    await report.check("checkout_personal", "submit", page, SUBMIT)


async def test_prestashop_selectors():
    report = Report()
    async with browser_session(headless=HEADLESS) as ctx:
        page = await ctx.new_page()
        await _run(page, report)

    print("\n=== selector health ===\n" + report.render())
    assert not report.failures, "Dead selectors found:\n" + report.render()
