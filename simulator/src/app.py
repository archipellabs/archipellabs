"""Application entrypoint — wire the external flows onto the runtime and run.

No FastAPI, no REST: the simulator is a runtime `App` of services. The
customer-arrivals producer and the customer-journey consumer share only the
`customer.arrival` name, so they can run together in this one process or be split
into separate deployments later via `enabled=` flags.

All knobs come from `Settings` (.env); see `src/config.py`.

    uv run python -m src.app
"""

from runtime import App

from src.config import settings
from src.external_flows.customer_arrivals.scheduler import service as arrivals_service
from src.external_flows.customer_journey.pool import service as journey_service
from src.infrastructure.db import run_migrations
from src.internal_flows.catalog.service import service as catalog_service
from src.internal_flows.payments.scheduler import service as payments_service
from src.internal_flows.stock.scheduler import service as stock_service


def build_app() -> App:
    # One runtime App holds every service. `include(..., enabled=)` is a WIRING
    # decision taken once: a service left out here is never constructed and its
    # lifespan never runs, which is how `journey_enabled=False` keeps Chromium
    # from launching at all. To pause something that IS mounted, without a
    # restart, use a runtime switch instead (`runtime.switches`).
    # `config=` is the per-service settings bag it reads from its `Context`.
    app = App(redis=settings.redis_url, namespace=settings.namespace)

    # Executant of customer.arrival: drives a browser through a PrestaShop journey.
    app.include(
        journey_service,
        enabled=settings.journey_enabled,
        config={
            "headless": settings.headless,
            "browser_no_sandbox": settings.browser_no_sandbox,
            "base_url": settings.shop_base_url,
            "fast": settings.fast,
            # Activity DB (chart data): the service opens this once in its lifespan
            # and records every journey run through it — core infrastructure,
            # always on.
            "dsn": settings.simulatordb_url,
        },
    )

    # Internal (shop-side) services: keep the catalog/stock in sync with the
    # storefront. The catalog service holds both the sync action and the doctor
    # that calls it; the doctor keeps its own flag, applied at registration.
    app.include(catalog_service, enabled=settings.catalog_enabled)
    app.include(stock_service, enabled=settings.stock_enabled)
    app.include(payments_service, enabled=settings.payments_enabled)

    # Producer of customer.arrival: dispatches simulated arrivals on a timer. Off
    # by default (arrivals_enabled) so the app can run consumer-only.
    app.include(
        arrivals_service,
        enabled=settings.arrivals_enabled,
        config={
            "market_mix": settings.market_mix,
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
