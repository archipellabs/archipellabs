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
from src.external_flows.customer_journey.journey import run_customer_journey
from src.external_flows.topics import Topic

log = logging.getLogger("simulator.customer_journey")


@asynccontextmanager
async def browser_lifespan(config: Config) -> AsyncIterator[Resources]:
    if not config.get("base_url"):
        raise ValueError("customer-journey: 'base_url' is required in config")
    # Imported lazily so the module can be inspected (topology, tests) without
    # Playwright installed.
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=config.get("headless", True))
    try:
        yield {"browser": browser}
    finally:
        await browser.close()
        await pw.stop()


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
    context = await ctx.resources["browser"].new_context(ignore_https_errors=True)
    try:
        await run_customer_journey(
            context,
            ctx.config["base_url"],
            journey=journey,
            guest=arrival.intent.customer,
            fast=ctx.config.get("fast", False),
            flow_id=arrival.id,
        )
    finally:
        await context.close()
