"""Terminal state for abandonment journeys: emit session_abandoned and stop."""

from src.external_flows.customer_journey.session import JourneySession


class ExitState:
    name = "exit"

    async def enter(self, session: JourneySession) -> str | None:
        from_state = session.data.get("last_state")
        session.data["abandoned"] = True
        session.data["abandoned_from"] = from_state
        session.log.emit("session_abandoned", from_state=from_state)
        return None
