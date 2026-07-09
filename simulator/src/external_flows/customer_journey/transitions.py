"""Journey graphs + registry: the catalogue of user stories the runner can execute."""

import random
from collections.abc import Callable
from dataclasses import dataclass

from src.external_flows.customer_journey.states.add_to_cart import AddToCartState
from src.external_flows.customer_journey.states.base import State
from src.external_flows.customer_journey.states.cart import CartState
from src.external_flows.customer_journey.states.catalog import CatalogState
from src.external_flows.customer_journey.states.category import CategoryState
from src.external_flows.customer_journey.states.checkout_address import (
    CheckoutAddressState,
)
from src.external_flows.customer_journey.states.checkout_payment import (
    CheckoutPaymentState,
)
from src.external_flows.customer_journey.states.checkout_personal import (
    CheckoutPersonalState,
)
from src.external_flows.customer_journey.states.checkout_shipping import (
    CheckoutShippingState,
)
from src.external_flows.customer_journey.states.confirmation import ConfirmationState
from src.external_flows.customer_journey.states.continue_shopping import (
    ContinueShoppingState,
)
from src.external_flows.customer_journey.states.exit import ExitState
from src.external_flows.customer_journey.states.landing import LandingState
from src.external_flows.customer_journey.states.proceed_to_checkout import (
    ProceedToCheckoutState,
)
from src.external_flows.customer_journey.states.product import ProductState

DEFAULT_CATEGORY = "Storage & Workshop"

Graph = tuple[dict[str, State], str]


# ── Journey graphs ───────────────────────────────────────────────────────────


def guest_checkout_graph(*, category: str = DEFAULT_CATEGORY) -> Graph:
    """One product → full funnel → order confirmation."""
    states: dict[str, State] = {
        "landing": LandingState(next_state="category"),
        "category": CategoryState(category_name=category, next_state="catalog"),
        "catalog": CatalogState(next_state="product"),
        "product": ProductState(next_state="add_to_cart"),
        "add_to_cart": AddToCartState(next_state="proceed_to_checkout"),
        "proceed_to_checkout": ProceedToCheckoutState(next_state="cart"),
        "cart": CartState(next_state="checkout_personal"),
        "checkout_personal": CheckoutPersonalState(next_state="checkout_address"),
        "checkout_address": CheckoutAddressState(next_state="checkout_shipping"),
        "checkout_shipping": CheckoutShippingState(next_state="checkout_payment"),
        "checkout_payment": CheckoutPaymentState(next_state="confirmation"),
        "confirmation": ConfirmationState(),
    }
    return states, "landing"


def add_to_cart_abandon_graph(*, category: str = DEFAULT_CATEGORY) -> Graph:
    """Add a product, close the modal via "Continue shopping", leave."""
    states: dict[str, State] = {
        "landing": LandingState(next_state="category"),
        "category": CategoryState(category_name=category, next_state="catalog"),
        "catalog": CatalogState(next_state="product"),
        "product": ProductState(next_state="add_to_cart"),
        "add_to_cart": AddToCartState(next_state="continue_shopping"),
        "continue_shopping": ContinueShoppingState(next_state="exit"),
        "exit": ExitState(),
    }
    return states, "landing"


def multi_item_checkout_graph(
    *,
    first_category: str = DEFAULT_CATEGORY,
    second_category: str = DEFAULT_CATEGORY,
) -> Graph:
    """Two products via the "Continue shopping" loop, then full checkout.

    Note: when the two categories share an in-stock product (the default case
    on this shop, where Storage & Workshop has only "Chest" available), the
    second pass adds the same SKU again, producing a cart with quantity 2 of
    one line item. Pass two different category names to get two distinct SKUs.
    """
    states: dict[str, State] = {
        "landing": LandingState(next_state="category_1"),
        "category_1": CategoryState(
            category_name=first_category, next_state="catalog_1"
        ),
        "catalog_1": CatalogState(next_state="product_1"),
        "product_1": ProductState(next_state="add_to_cart_1"),
        "add_to_cart_1": AddToCartState(next_state="continue_shopping"),
        "continue_shopping": ContinueShoppingState(next_state="category_2"),
        "category_2": CategoryState(
            category_name=second_category, next_state="catalog_2"
        ),
        "catalog_2": CatalogState(next_state="product_2"),
        "product_2": ProductState(next_state="add_to_cart_2"),
        "add_to_cart_2": AddToCartState(next_state="proceed_to_checkout"),
        "proceed_to_checkout": ProceedToCheckoutState(next_state="cart"),
        "cart": CartState(next_state="checkout_personal"),
        "checkout_personal": CheckoutPersonalState(next_state="checkout_address"),
        "checkout_address": CheckoutAddressState(next_state="checkout_shipping"),
        "checkout_shipping": CheckoutShippingState(next_state="checkout_payment"),
        "checkout_payment": CheckoutPaymentState(next_state="confirmation"),
        "confirmation": ConfirmationState(),
    }
    return states, "landing"


# ── Registry + weighted selection ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class JourneySpec:
    name: str
    graph_factory: Callable[..., Graph]
    weight: float
    description: str


JOURNEYS: dict[str, JourneySpec] = {
    "guest_checkout": JourneySpec(
        name="guest_checkout",
        graph_factory=guest_checkout_graph,
        weight=0.25,
        description="One product → full funnel → order confirmation.",
    ),
    "add_to_cart_abandon": JourneySpec(
        name="add_to_cart_abandon",
        graph_factory=add_to_cart_abandon_graph,
        weight=0.50,
        description="Add a product, dismiss the modal via 'Continue shopping', exit.",
    ),
    "multi_item_checkout": JourneySpec(
        name="multi_item_checkout",
        graph_factory=multi_item_checkout_graph,
        weight=0.25,
        description="Two products via the 'Continue shopping' loop, then full checkout.",
    ),
}


def pick_journey(
    name: str | None = None,
    rng: random.Random | None = None,
) -> JourneySpec:
    """Pick a journey by name or by weighted random.

    Weights are taken from each JourneySpec; they do not need to sum to 1.
    Pass `rng=random.Random(seed)` for reproducible selection.
    """
    if name is not None:
        if name not in JOURNEYS:
            raise KeyError(f"Unknown journey {name!r}; available: {sorted(JOURNEYS)}")
        return JOURNEYS[name]

    chooser = rng if rng is not None else random
    names = list(JOURNEYS)
    weights = [JOURNEYS[n].weight for n in names]
    picked = chooser.choices(names, weights=weights, k=1)[0]
    return JOURNEYS[picked]
