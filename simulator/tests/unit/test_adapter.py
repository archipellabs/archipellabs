from src.external_flows.contracts import (
    CustomerArrivalEvent,
    CustomerIntent,
    CustomerIntentType,
    CustomerProfile,
    ProductIntent,
)
from src.external_flows.customer_journey.adapter import journey_from_arrival


def _profile() -> CustomerProfile:
    return CustomerProfile(
        firstname="A",
        lastname="B",
        email="a.b@example.com",
        address1="1 Street",
        city="Town",
        postcode="12345",
        phone="",
        country="US",
    )


def _event(intent_type: CustomerIntentType, n_products: int) -> CustomerArrivalEvent:
    return CustomerArrivalEvent.create(
        intent=CustomerIntent(
            type=intent_type,
            customer=_profile(),
            products=[
                ProductIntent(category="X", quantity=1) for _ in range(n_products)
            ],
        ),
    )


def test_browse_discover_maps_to_abandon():
    event = _event(CustomerIntentType.BROWSE_DISCOVER, 0)
    assert journey_from_arrival(event) == "add_to_cart_abandon"


def test_single_product_maps_to_guest_checkout():
    event = _event(CustomerIntentType.BUY_PRODUCTS, 1)
    assert journey_from_arrival(event) == "guest_checkout"


def test_multiple_products_maps_to_multi_item_checkout():
    event = _event(CustomerIntentType.BUY_PRODUCTS, 2)
    assert journey_from_arrival(event) == "multi_item_checkout"
