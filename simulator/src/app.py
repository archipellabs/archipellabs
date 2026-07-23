"""Application entrypoint — wire the external flows onto the runtime and run.

No FastAPI, no REST: the simulator is a runtime `App`. The customer-arrivals
Scheduler (producer) and the customer-journey Pool (consumer) talk only through
the `customer.arrival` Redis stream, so they can run together in this one process
or be split into separate deployments later via `enabled=` flags.

All knobs come from `Settings` (.env); see `src/config.py`.

    uv run python -m src.app
"""

from runtime import App

from src.config import settings
from src.external_flows.customer_arrivals.scheduler import scheduler
from src.external_flows.customer_journey.pool import pool as journey_pool
from src.infrastructure.db import run_migrations
from src.internal_flows.catalog.doctor import scheduler as catalog_doctor
from src.internal_flows.catalog.pool import pool as catalog_pool
from src.internal_flows.stock.scheduler import scheduler as stock_scheduler


def build_app() -> App:
    # One runtime App holds every flow; each `include(..., enabled=)` is a
    # kill-switch, so any flow can be turned off here (or split into its own
    # deployment later) without touching the others. `config=` is the per-flow
    # settings bag the flow reads from its `Context`.
    app = App(redis=settings.redis_url, namespace=settings.namespace)

    # Consumer of customer.arrival: drives a browser through a PrestaShop journey.
    app.include(
        journey_pool,
        enabled=settings.journey_enabled,
        config={
            "headless": settings.headless,
            "browser_no_sandbox": settings.browser_no_sandbox,
            "base_url": settings.shop_base_url,
            "fast": settings.fast,
            # Activity DB (chart data): the pool opens this once in its lifespan and
            # records every journey run through it — core infrastructure, always on.
            "dsn": settings.simulatordb_url,
        },
    )

    # Internal (shop-side) flows: keep the catalog/stock in sync with the storefront.
    app.include(catalog_pool, enabled=settings.catalog_enabled)
    app.include(catalog_doctor, enabled=settings.catalog_doctor_enabled)
    app.include(stock_scheduler, enabled=settings.stock_enabled)

    # Producer of customer.arrival: emits simulated arrivals on a timer. Off by
    # default (arrivals_enabled) so the app can run consumer-only.
    app.include(
        scheduler,
        enabled=settings.arrivals_enabled,
        config={
            "country": settings.country,
            "tick_seconds": settings.tick_seconds,
            "max_arrivals_per_tick": settings.max_arrivals_per_tick,
            "random_seed": settings.random_seed,
            "rate": {
                "base_arrivals_per_minute": settings.base_arrivals_per_minute,
                "timezone": settings.arrival_timezone,
            },
        },
    )
    return app


if __name__ == "__main__":
    # Bring the activity DB schema up to date before starting (idempotent). A fresh
    # DB or a newly added migration then needs only an app (re)start — no separate
    # migration step to run by hand or a one-off container to schedule.
    run_migrations()
    build_app().start()
