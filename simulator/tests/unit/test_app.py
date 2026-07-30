from src import app as app_module
from src.config import Settings
from src.external_flows.customer_arrivals.scheduler import arrivals_lifespan
from src.services.configuration import service as service_module
from src.services.configuration.service import configuration


async def test_arrivals_lifespan_builds_everything_the_tick_reads():
    """The lifespan's resources and the tick's reads are one contract.

    Nothing else covers it: the tick's unit tests supply their own resources, so a
    resource dropped here would first surface as a KeyError on the opening tick of
    a live run.
    """
    async with arrivals_lifespan({}) as resources:
        assert set(resources) == {"rate", "identities", "rng"}


async def test_the_arrival_curve_runs_on_the_market_clock(monkeypatch):
    """The daily/weekly shape follows the shop's market clock, not UTC.

    Without it the evening peak lands at the wrong hour, and a baseline with the
    wrong shape is worse than none: it makes a real dip look like a quiet spell.
    """
    monkeypatch.setenv("ARRIVAL_TIMEZONE", "America/Chicago")
    monkeypatch.setattr(service_module, "settings", Settings())

    async with arrivals_lifespan({}) as resources:
        assert resources["rate"].timezone == "America/Chicago"


def test_disabled_flags_keep_services_out_of_the_process(monkeypatch):
    """`include(enabled=False)` is a wiring decision, not a runtime pause: a
    service left out is never constructed and its lifespan never runs, which is
    what keeps Chromium from launching when the journey is off."""
    for flag in ("JOURNEY_ENABLED", "CATALOG_ENABLED", "STOCK_ENABLED"):
        monkeypatch.setenv(flag, "false")
    monkeypatch.setenv("PAYMENTS_ENABLED", "false")
    monkeypatch.setenv("ARRIVALS_ENABLED", "true")
    monkeypatch.setattr(service_module, "settings", Settings())

    names = {inc.service.name for inc in app_module.build_app()._services}

    # "configuration" survives every flag: it is the control plane, so a switch
    # that could turn it off would lock the door from the inside.
    assert names == {"customer-arrivals", "configuration"}


def test_build_app_points_the_configuration_at_the_activity_database():
    """`build_app` is the one place the process's configuration is given a source.

    Miss it and every tunable answers from the static layer forever — a portal
    that appears to save and never takes effect, with nothing in the logs.
    """
    assert configuration.has_database is False  # the test default: static-only

    app_module.build_app()

    assert configuration.has_database is True
