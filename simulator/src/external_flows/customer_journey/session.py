"""The shared state of one journey run, threaded through every state node.

Created once per run in `journey.py` and passed to each `state.enter(session)`.
Distinct from the runtime `Context` (resources/config/emit) the flow handlers
receive — this is the journey state machine's own working state.
"""

from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

from src.external_flows.contracts import CustomerProfile
from src.services.observability.service import FlowTrace


@dataclass
class JourneySession:
    page: Page
    base_url: str
    guest: CustomerProfile
    log: FlowTrace
    default_timeout_ms: int = 10_000
    # Random "think time" inserted between states to mimic a real user pausing
    # to read/decide. None disables it (fast mode for tests).
    think_time_ms: tuple[int, int] | None = (500, 2500)
    # Scratchpad shared between states (selected SKU, order ref, etc.).
    data: dict[str, Any] = field(default_factory=dict)
