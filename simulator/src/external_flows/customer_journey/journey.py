"""Public entrypoint for running a customer journey against a PrestaShop instance."""

import uuid
from typing import Any

from playwright.async_api import BrowserContext

from src.external_flows.contracts import CustomerProfile
from src.external_flows.customer_journey.runner import run
from src.external_flows.customer_journey.session import JourneySession
from src.external_flows.customer_journey.transitions import pick_journey
from src.services.observability.service import FlowTrace

DEFAULT_THINK_TIME_MS: tuple[int, int] = (500, 2500)


async def run_customer_journey(
    browser_context: BrowserContext,
    base_url: str,
    *,
    guest: CustomerProfile,
    journey: str | None = None,
    fast: bool = False,
    flow_id: str | None = None,
    think_time_ms: tuple[int, int] = DEFAULT_THINK_TIME_MS,
) -> dict[str, Any]:
    """Execute a customer journey and return a session summary.

    `guest` is the customer identity to check out as — always supplied by the
    caller (the arrival event carries it). `flow_id` tags the trace so one run can
    be grepped out of the logs (the consumer passes the arrival id); it defaults to
    a fresh id for standalone runs. When `journey` is None, one is picked at random
    weighted by the registry in `transitions.JOURNEYS`.

    Each step is traced via `FlowTrace`; the returned dict aggregates them with
    per-run metadata. The summary distinguishes:
      - `success`: ran without raising
      - `completed`: an order confirmation page was reached
      - `abandoned`: the journey terminated in an ExitState
    """
    spec = pick_journey(journey)

    flow_id = flow_id or f"s_{uuid.uuid4().hex[:12]}"
    trace = FlowTrace(flow_id)
    guest_payload = guest.model_dump()

    page = await browser_context.new_page()
    session = JourneySession(
        page=page,
        base_url=base_url,
        guest=guest,
        log=trace,
        think_time_ms=None if fast else think_time_ms,
    )

    trace.emit(
        "session_started",
        base_url=base_url,
        journey=spec.name,
        guest=guest_payload,
    )

    states, start = spec.graph_factory()
    error: dict[str, str] | None = None
    try:
        await run(states, start, session)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        # Capture the last URL before closing the page — ConfirmationState
        # already sets it on success, but on abandon/error we want it too.
        if "final_url" not in session.data and not page.is_closed():
            session.data["final_url"] = page.url
        completed = bool(session.data.get("confirmed"))
        abandoned = bool(session.data.get("abandoned"))
        trace.emit(
            "session_finished",
            success=error is None,
            completed=completed,
            abandoned=abandoned,
            error=error,
        )
        await page.close()

    return {
        "flow_id": flow_id,
        "journey": spec.name,
        "success": error is None,
        "completed": bool(session.data.get("confirmed")),
        "abandoned": bool(session.data.get("abandoned")),
        "abandoned_from": session.data.get("abandoned_from"),
        "error": error,
        "guest": guest_payload,
        "order_reference": session.data.get("order_reference"),
        "selected_product": session.data.get("selected_product"),
        "cart_count": session.data.get("cart_count"),
        "final_url": session.data.get("final_url"),
        "events": trace.events,
    }
