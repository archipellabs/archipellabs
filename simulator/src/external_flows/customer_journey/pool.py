"""customer_journey — consumer (Pool) of Topic.CUSTOMER_ARRIVAL.

The pool's lifespan owns a single shared Chromium process (POOL scope, opened
once). Each arrival event is one isolated simulated user: the flow opens a fresh
browser context, translates the business intent into a concrete PrestaShop
journey, runs the Playwright state machine, then tears the context down.
Concurrency is bounded by the pool's `max_slots` semaphore.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from runtime import Config, Context, Event, Pool, Resources

from src.config import settings
from src.external_flows.contracts import CustomerArrivalEvent
from src.external_flows.customer_journey.adapter import journey_from_arrival
from src.external_flows.customer_journey.devices import (
    HIDE_CLIENT_HINTS_SCRIPT,
    context_kwargs,
)
from src.external_flows.customer_journey.journey import run_customer_journey
from src.external_flows.customer_journey.repository.journey_activity import (
    JourneyActivityRepository,
)
from src.external_flows.topics import Topic
from src.infrastructure.db import make_engine, make_sessionmaker

log = logging.getLogger("simulator.customer_journey")

# Sent on every simulated request so it can be told apart from real traffic (the
# gateway tags it `sim=1` in its access log). Deliberately tracker-agnostic;
# segmenting simulated vs real inside the analytics reports was left for a later
# stage, mappable from this header in the gateway without touching the simulator.
SIMULATOR_HEADER = {"X-Archipel-Simulator": "1"}


def browser_launch_options(config: Config) -> dict[str, Any]:
    """Translate pool config into the Chromium launch contract."""
    args = ["--no-sandbox"] if config.get("browser_no_sandbox", False) else []
    return {"headless": config.get("headless", True), "args": args}


def infrastructure_failure_summary(
    arrival: CustomerArrivalEvent,
    journey: str,
    started_at: datetime,
    error: Exception,
) -> dict[str, Any]:
    """Record an infrastructure failure without asking runtime 0.2 to retry it."""
    return {
        "flow_id": arrival.id,
        "journey": journey,
        "success": False,
        "completed": False,
        "abandoned": False,
        "abandoned_from": None,
        "error": {"type": type(error).__name__, "message": str(error)},
        "guest": arrival.intent.customer.model_dump(),
        "order_reference": None,
        "selected_product": None,
        "cart_count": None,
        "final_url": None,
        "started_at": started_at,
        "finished_at": datetime.now(UTC),
        "events": [],
    }


@asynccontextmanager
async def browser_lifespan(config: Config) -> AsyncIterator[Resources]:
    if not config.get("base_url"):
        raise ValueError("customer-journey: 'base_url' is required in config")
    # Imported lazily so the module can be inspected (topology, tests) without
    # Playwright installed.
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(**browser_launch_options(config))

    # Activity DB (chart data): opened once for the whole pool, like a database in a
    # FastAPI lifespan. Every journey run is recorded through this repository — it is
    # core infrastructure, not an optional add-on.
    engine = make_engine(config["dsn"])
    activity_repository = JourneyActivityRepository(make_sessionmaker(engine))
    resources: Resources = {
        "browser": browser,
        "devices": pw.devices,
        "activity_repository": activity_repository,
    }
    try:
        # Fail fast if the DB is unreachable or unmigrated, instead of letting every
        # arrival swallow the error in record() and silently write nothing.
        await activity_repository.verify_ready()
        yield resources
    finally:
        await browser.close()
        await pw.stop()
        await engine.dispose()


pool = Pool(
    "customer-journey", max_slots=settings.journey_slots, lifespan=browser_lifespan
)


@pool.flow(consumes=Topic.CUSTOMER_ARRIVAL)
async def run_arrival(ctx: Context, event: Event) -> None:
    # Runtime 0.2 has no pending-message reclaim yet: a handler exception leaves the
    # event pending, but does not currently redeliver it. Journey/state failures are
    # therefore converted to recorded summaries. Infrastructure failures are also
    # terminal observations for this synthetic load: record and acknowledge them
    # instead of leaving messages pending. Process crashes still need runtime reclaim;
    # duplicate-order protection must land before enabling that reclaim.
    try:
        arrival = CustomerArrivalEvent.model_validate(event)
    except ValidationError:
        # No dead-letter queue exists. Log and acknowledge malformed input instead
        # of leaving a permanently invalid event in the pending set.
        log.exception("dropping malformed %s event", Topic.CUSTOMER_ARRIVAL)
        return

    journey = journey_from_arrival(arrival)
    kwargs = context_kwargs(ctx.resources.get("devices", {}), arrival.visitor)
    # Mark this as simulated traffic with a tracker-agnostic header on every
    # request (readable in the gateway logs).
    kwargs["extra_http_headers"] = {
        **SIMULATOR_HEADER,
        **kwargs.get("extra_http_headers", {}),
    }
    started_at = datetime.now(UTC)
    context = None
    try:
        context = await ctx.resources["browser"].new_context(**kwargs)
        await context.add_init_script(HIDE_CLIENT_HINTS_SCRIPT)
        summary = await run_customer_journey(
            context,
            ctx.config["base_url"],
            journey=journey,
            guest=arrival.intent.customer,
            fast=ctx.config.get("fast", False),
            flow_id=arrival.id,
        )
    except Exception as exc:
        # Context setup or the journey runner can fail outside its state-level error
        # boundary. Treat that as an observed failed arrival rather than an implicit
        # retry, which could create a duplicate order after an ambiguous failure.
        log.exception("journey infrastructure failed for %s", arrival.id)
        summary = infrastructure_failure_summary(arrival, journey, started_at, exc)

    try:
        # Record the run into the activity DB (chart data). Best-effort inside the
        # repository, so a DB hiccup can't fail the journey.
        await ctx.resources["activity_repository"].record(
            arrival=arrival, summary=summary
        )
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                # Teardown happens after the observation is recorded. Do not strand
                # the queue event solely because Chromium failed to close a context.
                log.exception("browser context teardown failed for %s", arrival.id)
