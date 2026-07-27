"""Names exchanged between services — the queue contracts, named once.

A producer sends a `Topic`; the executant binds to the same `Topic` with
`@service.action(...)`. They share only this name, never a reference. `Topic` is
a `StrEnum`, so a member is a plain `str` everywhere the runtime expects one
(`call`, `dispatch`, `action`, stream naming).
"""

from enum import StrEnum


class Topic(StrEnum):
    CUSTOMER_ARRIVAL = "customer.arrival"
