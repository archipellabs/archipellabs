"""Click the modal's "Continue shopping" button, dismissing the modal."""

from src.external_flows.customer_journey.session import JourneySession
from src.external_flows.customer_journey.states.selectors import CART_MODAL

# The modal footer holds a single <button> ("Continue shopping"); "Proceed to
# checkout" is an <a>, so this uniquely targets the continue action — and stays
# robust to Bootstrap churn (btn-secondary → btn-outline-primary,
# data-dismiss → data-bs-dismiss) across theme versions.
CONTINUE_BUTTON = f"{CART_MODAL} .modal-footer button"


class ContinueShoppingState:
    name = "continue_shopping"

    def __init__(self, next_state: str = "exit") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page

        btn = page.locator(CONTINUE_BUTTON).first
        await btn.wait_for(state="visible", timeout=session.default_timeout_ms)
        await btn.click()

        # Modal fade-out is animated; wait for it to disappear so subsequent
        # states (e.g. a category click in the header) aren't intercepted.
        await page.locator(CART_MODAL).first.wait_for(
            state="hidden", timeout=session.default_timeout_ms
        )
        session.log.emit("continue_shopping")
        return self._next
