"""customer_journey — the service executing Topic.CUSTOMER_ARRIVAL.

The service's lifespan owns a single shared Chromium process (SERVICE scope,
opened once). Each arrival is one isolated simulated user: the action opens a
fresh browser context, translates the business intent into a concrete PrestaShop
journey, runs the Playwright state machine, then tears the context down.
Concurrency is bounded by `max_slots` — here a RAM ceiling on browser contexts.

Playwright is the heaviest cost profile in the app, which is exactly why it is its
own service: a flood of browser sessions cannot starve the catalog's budget.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from runtime import Config, Context, Resources, Service

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
from src.services.configuration.service import configuration

log = logging.getLogger("simulator.customer_journey")

# Sent on every simulated request so it can be told apart from real traffic (the
# gateway tags it `sim=1` in its access log). Deliberately tracker-agnostic;
# segmenting simulated vs real inside the analytics reports was left for a later
# stage, mappable from this header in the gateway without touching the simulator.
SIMULATOR_HEADER = {"X-Archipel-Simulator": "1"}


def browser_launch_options(*, show_browser: bool, no_sandbox: bool) -> dict[str, Any]:
    """Translate the two browser settings into the Chromium launch contract.

    The one place the polarity flips: the setting is positive and opt-in
    (`DEBUG_SHOW_BROWSER`), Playwright's parameter is negative (`headless`).
    """
    return {
        "headless": not show_browser,
        "args": ["--no-sandbox"] if no_sandbox else [],
    }


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
    # Warm the configuration snapshot before the first customer, so `fast` is read
    # from the database rather than defaulted on the opening journeys.
    await configuration.refresh()

    if not configuration.get("shop_base_url"):
        raise ValueError("customer-journey: SHOP_BASE_URL is required")
    # Imported lazily so the module can be inspected (topology, tests) without
    # Playwright installed.
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        **browser_launch_options(
            show_browser=configuration.get("debug_show_browser"),
            no_sandbox=configuration.get("browser_no_sandbox"),
        )
    )

    # Activity DB (chart data): opened once for the whole pool, like a database in a
    # FastAPI lifespan. Every journey run is recorded through this repository — it is
    # core infrastructure, not an optional add-on.
    engine = make_engine(configuration.get("simulatordb_url"))
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


service = Service(
    "customer-journey",
    max_slots=configuration.get("journey_slots"),
    lifespan=browser_lifespan,
)


@service.action(Topic.CUSTOMER_ARRIVAL, params=CustomerArrivalEvent)
async def run_arrival(ctx: Context, arrival: CustomerArrivalEvent) -> None:
    # `params=` means the runtime validated this before the handler ran; a
    # malformed body never gets here, and comes back to the producer as a typed
    # ParamsInvalid instead of being logged and dropped in silence.
    #
    # Journey and state failures are still converted to recorded summaries rather
    # than raised. There is no reclaim, so raising would not retry — and a retry
    # after an ambiguous failure could place a duplicate order. Duplicate-order
    # protection has to land before this flow can tolerate redelivery.
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
            configuration.get("shop_base_url"),
            journey=journey,
            guest=arrival.intent.customer,
            # Read per journey, so a change applies to the next customer and
            # nothing already in flight.
            fast=configuration.get("fast"),
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
