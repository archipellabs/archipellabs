"""Checkout step 4: select a payment method, accept terms, confirm the order."""

from src.external_flows.customer_journey.session import JourneySession

SECTION = "#checkout-payment-step"
CHECK_OPTION = "input[data-module-name='ps_checkpayment']"
ANY_OPTION = ".payment-option input[type='radio']"
TERMS_CHECKBOX = (
    "input[id^='conditions_to_approve'], input[name^='conditions_to_approve']"
)
CONFIRM_SUBMIT = "#payment-confirmation button[type='submit']"


class CheckoutPaymentState:
    name = "checkout_payment"

    def __init__(self, next_state: str = "confirmation") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        # The payment step renders after the SPA processes the shipping submit;
        # wait on its section and on the first payment option before acting.
        await page.locator(SECTION).first.wait_for(
            state="visible", timeout=session.default_timeout_ms
        )
        await page.locator(ANY_OPTION).first.wait_for(
            state="visible", timeout=session.default_timeout_ms
        )

        # Prefer the "pay by check" sandbox option; fall back to whatever is offered.
        check_option = page.locator(CHECK_OPTION)
        if await check_option.count() > 0:
            await check_option.first.check()
            method = "ps_checkpayment"
        else:
            await page.locator(ANY_OPTION).first.check()
            method = "first_available"

        terms = page.locator(TERMS_CHECKBOX).first
        if await terms.count() > 0 and not await terms.is_checked():
            await terms.check()

        session.log.emit("payment_attempted", method=method)

        # The submit triggers a real navigation to /order-confirmation.
        async with page.expect_navigation(timeout=session.default_timeout_ms):
            await page.locator(CONFIRM_SUBMIT).first.click()
        return self._next
