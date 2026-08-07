"""Reading the order reference off the confirmation page.

The text below is copied from a real confirmation page on the public shop, not
composed for the test — the bug this covers was invisible precisely because
plausible-looking markup was assumed rather than captured.
"""

from src.external_flows.customer_journey.states.confirmation import (
    DETAILS_LIST,
    reference_in,
)

DETAILS = """Order details
Order reference: WFIBAGWDQ
Payment method: Bank transfer
Shipping method: TimberWorks Ground"""

FRENCH = """Détails de la commande
Référence de commande : WFIBAGWDQ
Moyen de paiement : Virement bancaire"""

PRODUCT_BLOCK = "Barrel\nReference: barrel\n$17.00"


def test_the_reference_is_read_from_the_details_block() -> None:
    assert reference_in(DETAILS) == "WFIBAGWDQ"


def test_the_product_reference_is_not_an_order_reference() -> None:
    """The regression, stated directly.

    `[class*='reference']` matched `order-confirmation__product-reference` and
    nothing else, so every recorded journey stored "Reference: barrel" — a product
    name — as its order reference. It was never right, and never failed.
    """
    assert reference_in(PRODUCT_BLOCK) is None


def test_a_translated_label_does_not_hide_the_reference() -> None:
    """The shop is going bilingual; matching the label would break on that day."""
    assert reference_in(FRENCH) == "WFIBAGWDQ"


def test_nothing_found_is_none_rather_than_a_guess() -> None:
    assert reference_in("") is None
    assert reference_in("Order details\nPayment method: Bank transfer") is None


def test_the_selector_targets_the_order_block_not_any_reference() -> None:
    """A guard on the selector itself, since the parsing above cannot see it.

    Scoping is what makes the extraction safe: run the same regex over the whole
    page and it would meet the bank's address, the shipping method and the
    product block before the order's own summary.
    """
    assert "order-confirmation__details-list" in DETAILS_LIST
    assert "[class*=" not in DETAILS_LIST, "back to a substring match on any class"
