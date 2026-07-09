"""Terminal state: detect the order confirmation page and capture the reference."""

from src.external_flows.customer_journey.session import JourneySession

# The order reference appears in a few possible containers depending on the
# PrestaShop theme version — match any class containing "reference".
ORDER_REFERENCE = "[class*='order-reference'], [class*='reference']"


class ConfirmationState:
    name = "confirmation"

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        url = page.url
        confirmed = "confirmation" in url

        order_ref = None
        ref_locator = page.locator(ORDER_REFERENCE).first
        if await ref_locator.count() > 0:
            order_ref = (await ref_locator.inner_text()).strip()

        session.data["order_reference"] = order_ref
        session.data["confirmed"] = confirmed
        session.data["final_url"] = url

        if confirmed:
            session.log.emit("order_created", order_reference=order_ref, url=url)
        else:
            session.log.emit("order_not_confirmed", url=url)

        return None
