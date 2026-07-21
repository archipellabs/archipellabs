"""The device adapter: envelope → new_context kwargs, with graceful fallbacks."""

from src.external_flows.contracts import VisitorEnvelope
from src.external_flows.customer_arrivals.envelope import DEVICE_POOL
from src.external_flows.customer_journey.devices import DEVICE_MAP, context_kwargs

# A stand-in for playwright's registry: every descriptor DEVICE_MAP references.
FAKE_DEVICES = {
    name: {
        "user_agent": f"ua of {name}",
        "viewport": {"width": 100, "height": 200},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
        "default_browser_type": "webkit",
    }
    for name, _ in DEVICE_MAP.values()
}


def _visitor(device: str = "iphone") -> VisitorEnvelope:
    return VisitorEnvelope(
        device=device, ip="128.95.104.7", city="Seattle", timezone="America/Los_Angeles"
    )


def test_every_producer_device_key_has_a_mapping():
    assert set(DEVICE_POOL) <= set(DEVICE_MAP)


def test_mapped_descriptor_names_exist_in_playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        missing = {name for name, _ in DEVICE_MAP.values()} - set(p.devices)
    assert not missing


def test_kwargs_realize_the_envelope():
    kwargs = context_kwargs(FAKE_DEVICES, _visitor())

    assert kwargs["user_agent"] == "ua of iPhone 15"
    assert kwargs["viewport"] == {"width": 100, "height": 200}
    assert kwargs["extra_http_headers"]["X-Forwarded-For"] == "128.95.104.7"
    # Client hints blanked so a tracker can't read the real engine from them.
    assert kwargs["extra_http_headers"]["Sec-CH-UA"] == ""
    assert kwargs["locale"] == "en-US"
    assert kwargs["timezone_id"] == "America/Los_Angeles"
    assert kwargs["ignore_https_errors"] is True
    assert "default_browser_type" not in kwargs  # not a new_context kwarg


def test_user_agent_override_wins_over_the_descriptor():
    kwargs = context_kwargs(FAKE_DEVICES, _visitor("desktop_chrome_mac"))
    assert "Macintosh" in kwargs["user_agent"]


def test_no_visitor_falls_back_to_todays_default_context():
    assert context_kwargs(FAKE_DEVICES, None) == {"ignore_https_errors": True}


def test_unknown_device_keeps_the_network_identity():
    kwargs = context_kwargs(FAKE_DEVICES, _visitor("smart_fridge"))
    assert "user_agent" not in kwargs
    assert kwargs["extra_http_headers"]["X-Forwarded-For"] == "128.95.104.7"
    assert kwargs["extra_http_headers"]["Sec-CH-UA"] == ""
    assert kwargs["timezone_id"] == "America/Los_Angeles"
