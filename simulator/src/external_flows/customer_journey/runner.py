"""Generic async state-machine runner."""

import asyncio
import random
import time
from collections.abc import Mapping

from src.external_flows.customer_journey.session import JourneySession
from src.external_flows.customer_journey.states.base import State


async def run(
    states: Mapping[str, State], start: str, session: JourneySession
) -> str | None:
    """Drive `session` through the state graph until a state returns None.

    Events use the dict key as `state` (not the state class's default name),
    so a graph can re-use the same state class under different keys
    (e.g. `category_1`, `category_2`). `session.data["last_state"]` is updated
    after every successful transition so terminal states like ExitState can
    record where the user left.
    """
    current: str | None = start
    last: str | None = None
    while current is not None:
        if current not in states:
            session.log.emit("state_unknown", state=current)
            raise KeyError(f"Unknown state: {current!r}")

        state = states[current]
        started = time.monotonic()
        session.log.emit("state_entered", state=current)
        try:
            next_state = await state.enter(session)
        except Exception as exc:
            session.log.emit(
                "state_failed",
                state=current,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        session.log.emit(
            "state_completed",
            state=current,
            duration_ms=int((time.monotonic() - started) * 1000),
            next=next_state,
        )
        last = current
        session.data["last_state"] = current
        current = next_state

        if current is not None and session.think_time_ms is not None:
            lo, hi = session.think_time_ms
            delay_ms = random.randint(lo, hi) if hi > lo else lo
            if delay_ms > 0:
                session.log.emit("thinking", duration_ms=delay_ms, before=current)
                await asyncio.sleep(delay_ms / 1000)
    return last
