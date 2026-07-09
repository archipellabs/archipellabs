"""Translate business customer intents into this site's journey implementation."""

from src.external_flows.contracts import (
    CustomerArrivalEvent,
    CustomerIntentType,
)


def journey_from_arrival(event: CustomerArrivalEvent) -> str:
    """Map business intent to the currently implemented PrestaShop journey."""

    if event.intent.type == CustomerIntentType.BROWSE_DISCOVER:
        return "add_to_cart_abandon"
    if len(event.intent.products) > 1:
        return "multi_item_checkout"
    return "guest_checkout"
