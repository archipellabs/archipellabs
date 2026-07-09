"""Event types exchanged between flows — the queue contracts, named once.

A producer emits a `Topic`; a consumer binds to the same `Topic` with
`@pool.flow(consumes=...)`. They share only this name, never a reference.
`Topic` is a `StrEnum`, so a member is a plain `str` everywhere the runtime
expects one (`emit`, `consumes`, stream naming).
"""

from enum import StrEnum


class Topic(StrEnum):
    CUSTOMER_ARRIVAL = "customer.arrival"
