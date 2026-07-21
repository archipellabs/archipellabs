"""Map abstract visitor device keys to concrete Playwright browser profiles.

The consumer-side counterpart of the producer's device vocabulary
(customer_arrivals/envelope.py), mirroring the intent → journey adapter. Every
profile runs on the pool's one Chromium process — a descriptor only shapes the
user-agent, viewport and touch fingerprint, so Safari/Firefox keys emulate those
browsers' *identity*, not their engine.
"""

from collections.abc import Mapping
from typing import Any

from src.external_flows.contracts import VisitorEnvelope

# The "Desktop Chrome" descriptor carries a Windows user-agent; the macOS
# variant differs only by UA. Chrome pins its macOS token to 10_15_7, so this
# string stays parseable by device detectors regardless of the actual OS.
_CHROME_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Chromium exposes its real identity ("HeadlessChrome") through client hints,
# regardless of the user-agent override, on two independent channels — and the
# launch flags that used to disable them (--disable-features=UserAgentClientHint)
# are dead in modern builds. We neutralize both channels at the context level so
# device detectors fall back to the spoofed user-agent:
#   - JS: hide navigator.userAgentData (the object a JS tracker reads for hints);
#   - HTTP: blank the Sec-CH-UA* request headers (empty ⇒ no client-hint data,
#     which is also what real Safari/Firefox send — none).
HIDE_CLIENT_HINTS_SCRIPT = (
    "Object.defineProperty(Navigator.prototype, 'userAgentData', "
    "{ get: () => undefined });"
)

# extra_http_headers can only set, not unset, so we send these empty — a blank
# Sec-CH-UA reads as "no client hints", same result as an absent header.
_BLANK_CLIENT_HINT_HEADERS = {
    "Sec-CH-UA": "",
    "Sec-CH-UA-Mobile": "",
    "Sec-CH-UA-Platform": "",
    "Sec-CH-UA-Full-Version-List": "",
    "Sec-CH-UA-Model": "",
}

# device key → (Playwright descriptor name, optional user-agent override)
DEVICE_MAP: dict[str, tuple[str, str | None]] = {
    "iphone": ("iPhone 15", None),
    "iphone_large": ("iPhone 14 Pro Max", None),
    "android_phone": ("Pixel 7", None),
    "android_phone_samsung": ("Galaxy S24", None),
    "ipad": ("iPad (gen 11)", None),
    "desktop_chrome_win": ("Desktop Chrome", None),
    "desktop_chrome_mac": ("Desktop Chrome", _CHROME_MAC_UA),
    "desktop_firefox_win": ("Desktop Firefox", None),
}


def context_kwargs(
    pw_devices: Mapping[str, dict[str, Any]], visitor: VisitorEnvelope | None
) -> dict[str, Any]:
    """`new_context` kwargs realizing a visitor's envelope.

    No envelope (older events) → today's plain context. An unknown device key or
    missing descriptor degrades to the default device but keeps the network
    identity (spoofed IP, locale, timezone) — the envelope's tracker-visible part.
    """
    kwargs: dict[str, Any] = {"ignore_https_errors": True}
    if visitor is None:
        return kwargs

    name, ua_override = DEVICE_MAP.get(visitor.device, (None, None))
    descriptor = pw_devices.get(name) if name is not None else None
    if descriptor is not None:
        kwargs |= {k: v for k, v in descriptor.items() if k != "default_browser_type"}
        if ua_override is not None:
            kwargs["user_agent"] = ua_override

    kwargs["extra_http_headers"] = {
        "X-Forwarded-For": visitor.ip,
        **_BLANK_CLIENT_HINT_HEADERS,
    }
    kwargs["locale"] = visitor.locale
    kwargs["timezone_id"] = visitor.timezone
    return kwargs
