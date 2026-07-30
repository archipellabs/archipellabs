"""Application entrypoint — wire the external flows onto the runtime and run.

No FastAPI, no REST: the simulator is a runtime `App` of services. The
customer-arrivals producer and the customer-journey consumer share only the
`customer.arrival` name, so they can run together in this one process or be split
into separate deployments later via `enabled=` flags.

Every knob is read through `configuration.get(...)`; see
`src/services/configuration/service.py`.

    uv run python -m src.app
"""

from runtime import App

from src.external_flows.customer_arrivals.scheduler import service as arrivals_service
from src.external_flows.customer_journey.pool import service as journey_service
from src.infrastructure.db import make_engine, make_sessionmaker, run_migrations
from src.internal_flows.catalog.service import service as catalog_service
from src.internal_flows.payments.scheduler import service as payments_service
from src.internal_flows.stock.scheduler import service as stock_service
from src.services.configuration.service import configuration
from src.technical_flows.configuration.actions import service as configuration_service


def build_app() -> App:
    # Point the configuration at the database that holds the runtime overrides.
    # Engine construction opens no connection, so this is safe before the loop
    # exists; the first read inside a lifespan is what actually connects.
    configuration.use(
        make_sessionmaker(make_engine(configuration.get("simulatordb_url")))
    )

    # One runtime App holds every service. `include(..., enabled=)` is a WIRING
    # decision taken once: a service left out here is never constructed and its
    # lifespan never runs, which is how `journey_enabled=False` keeps Chromium
    # from launching at all. To pause something that IS mounted, without a
    # restart, use a runtime switch instead (`runtime.switches`).
    app = App(
        redis=configuration.get("redis_url"),
        namespace=configuration.get("namespace"),
    )

    # The control plane. Always mounted and never gated by a flag: it is what
    # pauses the others, so a switch that could turn it off would lock the door
    # from the inside.
    app.include(configuration_service)

    # Executant of customer.arrival: drives a browser through a PrestaShop journey.
    app.include(journey_service, enabled=configuration.get("journey_enabled"))

    # Internal (shop-side) services: keep the catalog/stock in sync with the
    # storefront. The catalog service holds both the sync action and the doctor
    # that calls it; the doctor keeps its own flag, applied at registration.
    app.include(catalog_service, enabled=configuration.get("catalog_enabled"))
    app.include(stock_service, enabled=configuration.get("stock_enabled"))
    app.include(payments_service, enabled=configuration.get("payments_enabled"))

    # Producer of customer.arrival: dispatches simulated arrivals on a timer. Off
    # by default (arrivals_enabled) so the app can run consumer-only.
    app.include(arrivals_service, enabled=configuration.get("arrivals_enabled"))
    return app


if __name__ == "__main__":
    # Bring the activity DB schema up to date before starting (idempotent). A fresh
    # DB or a newly added migration then needs only an app (re)start — no separate
    # migration step to run by hand or a one-off container to schedule.
    run_migrations()
    build_app().start()
