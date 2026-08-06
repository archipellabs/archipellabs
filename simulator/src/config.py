from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.external_flows.customer_arrivals.envelope import LOCATIONS

NonNegativeFiniteFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(ge=0)]


def validate_market_mix(value: dict[str, NonNegativeFiniteFloat]) -> dict[str, float]:
    """Accept only usable, known markets with a positive total weight."""
    unknown = sorted(set(value) - set(LOCATIONS))
    if unknown:
        raise ValueError(f"unknown market(s) {unknown}; known: {sorted(LOCATIONS)}")
    if sum(value.values()) <= 0:
        raise ValueError("market mix needs a positive total weight")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Admin API (OAuth2)
    prestashop_base_url: str = "https://localhost/admin-api"
    prestashop_client_id: str = ""
    prestashop_client_secret: str = ""
    prestashop_scopes: str = (
        "attribute_group_read attribute_group_write "
        "attribute_read attribute_write "
        "category_read category_write "
        "product_read product_write"
    )

    # Webservice API (Basic auth)
    prestashop_webservice_url: str = "https://localhost/api"
    prestashop_webservice_api_key: str = ""
    prestashop_webservice_language_id: str = "1"

    # Shop front-end (used by browser simulation)
    shop_base_url: str = "https://localhost"

    # Runtime (Redis-backed producer/consumer)
    redis_url: str = "redis://localhost:6379/0"
    namespace: str = "sim"
    """Prefixes every runtime key. Deliberately not empty: the storefront stack
    shares this Redis, and the runtime's switch registry lives under a fixed key,
    so an unprefixed deployment can have a service silently paused by anything
    else that writes one — another environment, a stray redis-cli, a test run.
    Override per environment (NAMESPACE=staging) to isolate them from each other."""

    # Flow kill-switches (App.include enabled=) — toggle each flow on/off.
    journey_enabled: bool = True
    arrivals_enabled: bool = False  # off by default — enable to generate traffic
    catalog_enabled: bool = True
    stock_enabled: bool = True
    payments_enabled: bool = True
    catalog_doctor_enabled: bool = True

    # stock refill flow: how often to top up tracked products (runtime duration)
    stock_check_interval: str = "1m"
    # payment settlement: how often to accept the waiting bank wires. Nothing else
    # ever moves an order out of "Awaiting bank wire payment", so without this the
    # shop takes orders that are never paid.
    payment_check_interval: str = "5m"
    # catalog doctor: how often to check for drift and reconcile (runtime duration)
    catalog_doctor_interval: str = "5m"

    # customer_journey consumer (browser pool)
    journey_slots: int = 4
    debug_show_browser: bool = False
    """Watch a simulated customer shop, instead of running Chromium headless.

    A debugging aid, off by default and named for it: a visible browser needs a
    display, so leaving it on is how a container gets a stack that runs fine
    locally and cannot launch at all in the compose stack."""
    fast: bool = False
    browser_no_sandbox: bool = False  # containers need Chromium's --no-sandbox

    # customer_arrivals producer
    market_mix: dict[str, NonNegativeFiniteFloat] = {"US": 0.75, "CA": 0.25}
    """Which markets the shop draws traffic from, and in what proportion.
    Relative weights, not percentages. Set as JSON: MARKET_MIX='{"US": 1}'.
    Every key needs a location catalogue in customer_arrivals/envelope.py and an
    *active* country in the shop, or its customers cannot check out."""
    tick_seconds: float = 5.0
    base_arrivals_per_minute: NonNegativeFiniteFloat = 3.0
    arrival_profile: Literal["curve", "flat"] = "curve"
    """The shape of the arrival rate: following the clock, or held level.

    `curve` is the shop being simulated. `flat` is for experiments: under the
    curve, two campaigns launched hours apart meet shops that differ by more than
    5x, so their results are not comparable — and the shop's state has more than
    once turned out to be the dominant variable in a measurement. `flat` is the
    rate, not the traffic: Poisson remains, and is then the only variation."""
    # Daily/hourly traffic curves follow the simulated market's local clock.
    arrival_timezone: str = "America/Chicago"
    max_arrivals_per_tick: NonNegativeInt = 1000
    random_seed: int | None = None  # set for a reproducible producer run

    # Activity database (PostgreSQL) — records each journey run for charts. Core
    # infrastructure, always wired (like a database in a FastAPI app): bring
    # `simulatordb` up and run `alembic upgrade head` before starting. A LOCAL run
    # uses this localhost DSN; in Docker, SIMULATORDB_URL overrides it with the
    # in-container hostname.
    simulatordb_url: str = (
        "postgresql+psycopg://simulator:changeme_demo@localhost:5432/simulator"
    )

    _validate_market_mix = field_validator("market_mix")(validate_market_mix)


settings = Settings()
