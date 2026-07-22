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


@asynccontextmanager
async def browser_lifespan(config: Config) -> AsyncIterator[Resources]:
    if not config.get("base_url"):
        raise ValueError("customer-journey: 'base_url' is required in config")
    # Imported lazily so the module can be inspected (topology, tests) without
    # Playwright installed.
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=config.get("headless", True))

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
    # AT-LEAST-ONCE delivery: a crash before ack redelivers the event, which would
    # re-run a full checkout (not idempotent → a possible duplicate order). Accepted
    # for a load simulator; revisit with a dedup key if real orders ever matter.
    try:
        arrival = CustomerArrivalEvent.model_validate(event)
    except ValidationError:
        # No dead-letter queue exists, so a malformed "poison" event would be
        # redelivered forever. Log and ack it (return) instead of raising.
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
    context = await ctx.resources["browser"].new_context(**kwargs)
    await context.add_init_script(HIDE_CLIENT_HINTS_SCRIPT)
    try:
        summary = await run_customer_journey(
            context,
            ctx.config["base_url"],
            journey=journey,
            guest=arrival.intent.customer,
            fast=ctx.config.get("fast", False),
            flow_id=arrival.id,
        )
        # Record the run into the activity DB (chart data). Best-effort inside the
        # repository, so a DB hiccup can't fail the journey.
        await ctx.resources["activity_repository"].record(
            arrival=arrival, summary=summary
        )
    finally:
        await context.close()
