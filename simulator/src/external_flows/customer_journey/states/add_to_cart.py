"""Click the add-to-cart button and wait for the confirmation modal."""

import re

from src.external_flows.customer_journey.session import JourneySession
from src.external_flows.customer_journey.states.selectors import CART_MODAL

ADD_TO_CART_BUTTON = "button[data-button-action='add-to-cart']"
# The modal's "There is/are N item(s) in your cart." line — we regex the count out.
CART_MODAL_PRODUCT_COUNT = f"{CART_MODAL} .blockcart-modal__nb-products"


class AddToCartState:
    name = "add_to_cart"

    def __init__(self, next_state: str = "proceed_to_checkout") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        product = session.data.get("selected_product", {})

        add_btn = page.locator(ADD_TO_CART_BUTTON).first
        await add_btn.wait_for(state="visible", timeout=session.default_timeout_ms)
        await add_btn.click()
        session.log.emit("add_to_cart", product_name=product.get("name"))

        modal = page.locator(CART_MODAL).first
        await modal.wait_for(state="visible", timeout=session.default_timeout_ms)

        # Parse the modal's "There are N items in your cart" line for the running count.
        cart_count: int | None = None
        count_el = page.locator(CART_MODAL_PRODUCT_COUNT).first
        if await count_el.count() > 0:
            match = re.search(r"\d+", await count_el.inner_text())
            if match:
                cart_count = int(match.group())
        session.data["cart_count"] = cart_count
        session.log.emit("cart_modal_shown", cart_count=cart_count)

        return self._next
