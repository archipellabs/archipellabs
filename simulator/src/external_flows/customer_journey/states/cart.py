"""Cart → checkout: click "proceed to checkout" on the cart page."""

from src.external_flows.customer_journey.session import JourneySession

# The cart "proceed to checkout" is a <button>, not a link — match only the
# enabled one (disabled appears while the cart is updating).
PROCEED_TO_CHECKOUT_BUTTON = ".checkout .btn-primary:not([disabled])"


class CartState:
    name = "cart"

    def __init__(self, next_state: str = "checkout_personal") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        session.log.emit("cart_viewed", url=page.url)

        proceed = page.locator(PROCEED_TO_CHECKOUT_BUTTON).first
        await proceed.wait_for(state="visible", timeout=session.default_timeout_ms)
        await proceed.click()
        session.log.emit("checkout_started")
        return self._next
