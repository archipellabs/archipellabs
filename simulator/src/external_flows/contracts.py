"""Event contracts exchanged between flows — the shared API of the queue.

These models are the payload schema behind a `Topic` (see `topics.py`): the
producer builds and `model_dump(mode="json")`s them onto the stream, every
consumer `model_validate`s them back. They belong to neither side — both the
`customer_arrivals` producer and the `customer_journey` consumer depend on this
module, never on each other. The producer remains the authority on the schema;
this is just its neutral home.

The event is a pure business arrival: who arrived and what they want. Where the
storefront lives and how fast to drive it are the consumer's concern (its config),
not the event's.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field


class CustomerIntentType(StrEnum):
    BUY_PRODUCTS = "buy_products"
    BROWSE_DISCOVER = "browse_discover"


class CustomerProfile(BaseModel):
    firstname: str
    lastname: str
    email: str
    address1: str
    city: str
    postcode: str
    phone: str
    country: str


class VisitorEnvelope(BaseModel):
    """The technical guise a visitor arrives under — device, network, locality.

    Website-agnostic on purpose: `device` is an abstract key from the producer's
    catalogue (customer_arrivals/envelope.py); the consumer maps it to a concrete
    browser profile (customer_journey/devices.py), mirroring intent → journey.

    `city` is the *intended* location label; the analytics tracker geolocates the
    IP itself and may record a different nearby city — that divergence is a
    deliberate signal of the accuracy lost to a free GeoIP database, not a bug.
    `timezone` is what we actually drive (sent to the browser).
    """

    device: str
    ip: str
    city: str
    timezone: str
    locale: str = "en-US"


class ProductIntent(BaseModel):
    sku: str | None = None
    name: str | None = None
    category: str | None = None
    quantity: int = Field(default=1, ge=1)


class CustomerIntent(BaseModel):
    type: CustomerIntentType
    customer: CustomerProfile
    products: list[ProductIntent] = Field(default_factory=list)


class CustomerArrivalEvent(BaseModel):
    id: str
    created_at: datetime
    intent: CustomerIntent
    # Optional so events already on the stream keep validating.
    visitor: VisitorEnvelope | None = None

    @classmethod
    def create(
        cls, *, intent: CustomerIntent, visitor: VisitorEnvelope | None = None
    ) -> Self:
        return cls(
            id=f"a_{uuid.uuid4().hex[:12]}",
            created_at=datetime.now(UTC),
            intent=intent,
            visitor=visitor,
        )
