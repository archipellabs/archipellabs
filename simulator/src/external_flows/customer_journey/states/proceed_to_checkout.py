"""Click the modal's "Proceed to checkout" link and land on the cart page."""

from src.external_flows.customer_journey.session import JourneySession
from src.external_flows.customer_journey.states.selectors import CART_MODAL

PROCEED_LINK = f"{CART_MODAL} a.btn-primary"


class ProceedToCheckoutState:
    name = "proceed_to_checkout"

    def __init__(self, next_state: str = "cart") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        proceed = page.locator(PROCEED_LINK).first
        await proceed.wait_for(state="visible", timeout=session.default_timeout_ms)
        session.log.emit("modal_proceed_clicked")
        await proceed.click()
        await page.wait_for_load_state(
            "domcontentloaded", timeout=session.default_timeout_ms
        )
        return self._next
