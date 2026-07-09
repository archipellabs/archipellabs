"""State protocol for the customer-journey state machine."""

from typing import Protocol, runtime_checkable

from src.external_flows.customer_journey.session import JourneySession


@runtime_checkable
class State(Protocol):
    """A single node in the journey graph.

    `enter` performs the work for this state and returns the name of the next
    state to transition into, or None to terminate the journey.
    """

    name: str

    async def enter(self, session: JourneySession) -> str | None: ...
