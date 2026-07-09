"""Product page: emit a product_viewed event. No mutation, no clicks."""

from src.external_flows.customer_journey.session import JourneySession


class ProductState:
    name = "product"

    def __init__(self, next_state: str = "add_to_cart") -> None:
        self._next = next_state

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        product = session.data.get("selected_product", {})
        session.log.emit(
            "product_viewed",
            url=page.url,
            product_name=product.get("name"),
        )
        return self._next
