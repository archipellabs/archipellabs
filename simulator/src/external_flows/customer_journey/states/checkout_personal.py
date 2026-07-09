"""Checkout step 1: fill the guest personal-information form.

The checkout is a SPA — wait on the step's landmark element, not on load events.
"""

from src.external_flows.customer_journey.session import JourneySession

PERSONAL_SECTION = "#checkout-personal-information-step"
GUEST_TAB_LINK = "[data-link-action='display-guest-form']"
CUSTOMER_FORM = "#customer-form"
FIELD_FIRSTNAME = "#field-firstname"
FIELD_LASTNAME = "#field-lastname"
FIELD_EMAIL = "#field-email"
# Both required checkboxes must be ticked before the form will submit.
REQUIRED_CHECKBOXES = (
    f"{CUSTOMER_FORM} input[type='checkbox'][name='customer_privacy'], "
    f"{CUSTOMER_FORM} input[type='checkbox'][name='psgdpr']"
)
SUBMIT = f"{CUSTOMER_FORM} button[type='submit']"


class CheckoutPersonalState:
    name = "checkout_personal"

    def __init__(self, next_state: str = "checkout_address") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        await page.locator(PERSONAL_SECTION).first.wait_for(
            state="visible", timeout=session.default_timeout_ms
        )

        # If the form starts on the "sign in" tab, switch to guest.
        guest_tab = page.locator(GUEST_TAB_LINK)
        if await guest_tab.count() > 0 and await guest_tab.first.is_visible():
            await guest_tab.first.click()

        firstname = page.locator(FIELD_FIRSTNAME)
        await firstname.wait_for(state="visible", timeout=session.default_timeout_ms)

        guest = session.guest
        await firstname.fill(guest.firstname)
        await page.fill(FIELD_LASTNAME, guest.lastname)
        await page.fill(FIELD_EMAIL, guest.email)

        for checkbox in await page.locator(REQUIRED_CHECKBOXES).all():
            if not await checkbox.is_checked():
                await checkbox.check()

        session.log.emit(
            "checkout_step_completed",
            step="personal_information",
            email=guest.email,
        )

        await page.locator(SUBMIT).first.click()
        return self._next
