from src import app as app_module


def test_arrival_scheduler_receives_market_timezone(monkeypatch):
    monkeypatch.setattr(app_module.settings, "arrivals_enabled", True)
    monkeypatch.setattr(app_module.settings, "arrival_timezone", "America/Chicago")

    app = app_module.build_app()
    inclusion = next(
        item for item in app._schedulers if item.scheduler.name == "customer-arrivals"
    )

    assert inclusion.config["rate"]["timezone"] == "America/Chicago"
