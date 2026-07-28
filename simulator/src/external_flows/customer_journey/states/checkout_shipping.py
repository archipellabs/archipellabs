"""Checkout step 3: confirm the shipping method."""

from src.external_flows.customer_journey.session import JourneySession

SECTION = "#checkout-delivery-step"
FORM = "#js-delivery"
CARRIER_RADIO = f"{FORM} input[type='radio']"
SUBMIT = "button[name='confirmDeliveryOption']"


class CheckoutShippingState:
    name = "checkout_shipping"

    def __init__(self, next_state: str = "checkout_payment") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        # Wait for the section first (always rendered); the inner form may
        # appear slightly later as PrestaShop fetches carrier options.
        await page.locator(SECTION).first.wait_for(
            state="visible", timeout=session.default_timeout_ms
        )
        await page.locator(FORM).first.wait_for(
            state="visible", timeout=session.default_timeout_ms
        )

        # How many carriers this customer was actually offered. Coverage differs
        # by market — a shop can serve one country and not its neighbour — so
        # this is the number that moves when shipping breaks for one of them,
        # while every other signal on the page stays exactly the same.
        offered = await page.locator(CARRIER_RADIO).count()
        session.log.emit("checkout_shipping_options", count=offered)

        carrier = page.locator(CARRIER_RADIO).first
        if offered > 0 and not await carrier.is_checked():
            await carrier.check()

        session.log.emit("checkout_step_completed", step="shipping")

        await page.locator(SUBMIT).first.click()
        return self._next
