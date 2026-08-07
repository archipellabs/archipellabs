"""Terminal state: detect the order confirmation page and capture the reference."""

import re

from src.external_flows.customer_journey.session import JourneySession

DETAILS_LIST = ".order-confirmation__details-list"
"""The order's own summary block — reference, payment method, total.

**Scoped, where the old selector was broad.** This used to be
`[class*='order-reference'], [class*='reference']`, justified in a comment as
matching "any class containing reference" so it would survive a theme change.
The confirmation page has exactly one element whose class contains that word:

    <p class="order-confirmation__product-reference">Reference: barrel</p>

— the PRODUCT reference. Nothing on the page carries an `order-reference` class
at all, so the first half of that selector never matched anything and the second
half matched the wrong thing, on every order, deterministically. Every journey
ever recorded carries `order_reference: "Reference: barrel"` — the product name.

Broadening a selector to tolerate an unknown future theme is what made it wrong
against the present one. Narrow and specific fails visibly; broad and permissive
returns a confident wrong answer.
"""

REFERENCE = re.compile(r"\b([A-Z]{9})\b")
"""PrestaShop's reference format: nine uppercase letters, no digits.

Matched by shape rather than by the label beside it, because that label is
translated — the shop is going bilingual, and "Order reference:" becomes
"Référence de commande :" without warning. The shape does not move.
"""


def reference_in(details: str) -> str | None:
    """The order reference within the details block, or None if it is not there.

    None rather than a best guess: an investigation that reads a wrong reference
    has no way to discover it is wrong, while a missing one is obvious.
    """
    found = REFERENCE.search(details)
    return found.group(1) if found else None


class ConfirmationState:
    name = "confirmation"

    async def enter(self, session: JourneySession) -> str | None:
        page = session.page
        url = page.url
        confirmed = "confirmation" in url

        order_ref = None
        details = page.locator(DETAILS_LIST).first
        if await details.count() > 0:
            order_ref = reference_in(await details.inner_text())

        session.data["order_reference"] = order_ref
        session.data["confirmed"] = confirmed
        session.data["final_url"] = url

        if confirmed:
            session.log.emit("order_created", order_reference=order_ref, url=url)
        else:
            session.log.emit("order_not_confirmed", url=url)

        return None
