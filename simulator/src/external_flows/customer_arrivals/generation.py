"""Build one customer-arrival event — who arrives and what they want.

The producer's business logic, kept out of the thin scheduler wiring. The
scheduler decides *how many* arrive each tick (rate × Poisson); this decides
*who* each one is and *what* they intend to do.
"""

import random

from src.external_flows.contracts import (
    CustomerArrivalEvent,
    CustomerIntent,
    CustomerIntentType,
    ProductIntent,
)
from src.external_flows.customer_arrivals.identity_pool import IdentityPool

# The business category a buying customer intends to shop. Producer-side only —
# the consumer maps it to a concrete storefront category, so this is deliberately
# NOT shared with the journey graph's category (that would couple the two sides).
INTENT_CATEGORY = "Storage & Workshop"
BUY_PROBABILITY = 0.55
SECOND_PRODUCT_PROBABILITY = 0.25


def build_arrival(identities: IdentityPool, rng: random.Random) -> CustomerArrivalEvent:
    """One arrival: a customer (new or returning) carrying a business intent."""
    customer = identities.pick()

    intent_type = (
        CustomerIntentType.BUY_PRODUCTS
        if rng.random() < BUY_PROBABILITY
        else CustomerIntentType.BROWSE_DISCOVER
    )
    products: list[ProductIntent] = []
    if intent_type == CustomerIntentType.BUY_PRODUCTS:
        products.append(ProductIntent(category=INTENT_CATEGORY, quantity=1))
        if rng.random() < SECOND_PRODUCT_PROBABILITY:
            products.append(ProductIntent(category=INTENT_CATEGORY, quantity=1))

    intent = CustomerIntent(type=intent_type, customer=customer, products=products)
    return CustomerArrivalEvent.create(intent=intent)
