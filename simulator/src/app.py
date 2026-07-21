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
from src.internal_flows.catalog.doctor import scheduler as catalog_doctor
from src.internal_flows.catalog.pool import pool as catalog_pool
from src.internal_flows.stock.scheduler import scheduler as stock_scheduler


def build_app() -> App:
    app = App(redis=settings.redis_url, namespace=settings.namespace)
    app.include(
        journey_pool,
        enabled=settings.journey_enabled,
        config={
            "headless": settings.headless,
            "base_url": settings.shop_base_url,
            "fast": settings.fast,
        },
    )
    app.include(catalog_pool, enabled=settings.catalog_enabled)
    app.include(catalog_doctor, enabled=settings.catalog_doctor_enabled)
    app.include(stock_scheduler, enabled=settings.stock_enabled)
    app.include(
        scheduler,
        enabled=settings.arrivals_enabled,
        config={
            "country": settings.country,
            "tick_seconds": settings.tick_seconds,
            "max_arrivals_per_tick": settings.max_arrivals_per_tick,
            "random_seed": settings.random_seed,
            "rate": {"base_arrivals_per_minute": settings.base_arrivals_per_minute},
        },
    )
    return app


if __name__ == "__main__":
    build_app().start()
