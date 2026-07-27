from src import app as app_module


def test_arrival_service_receives_market_timezone(monkeypatch):
    monkeypatch.setattr(app_module.settings, "arrivals_enabled", True)
    monkeypatch.setattr(app_module.settings, "arrival_timezone", "America/Chicago")

    app = app_module.build_app()
    inclusion = next(
        item for item in app._services if item.service.name == "customer-arrivals"
    )

    assert inclusion.config["rate"]["timezone"] == "America/Chicago"


def test_disabled_flags_keep_services_out_of_the_process(monkeypatch):
    """`include(enabled=False)` is a wiring decision, not a runtime pause: a
    service left out is never constructed and its lifespan never runs, which is
    what keeps Chromium from launching when the journey is off."""
    for flag in ("journey_enabled", "catalog_enabled", "stock_enabled"):
        monkeypatch.setattr(app_module.settings, flag, False)
    monkeypatch.setattr(app_module.settings, "arrivals_enabled", True)

    names = {inc.service.name for inc in app_module.build_app()._services}

    assert names == {"customer-arrivals"}
