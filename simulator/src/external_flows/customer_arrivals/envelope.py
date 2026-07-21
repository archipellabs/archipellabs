"""Visitor envelopes — which device, and from where, a simulated customer arrives.

Universal shape data, constants not config (like the rate curves in rate.py): a
fixed catalogue of US locations and a device mix roughly shaped like US
e-commerce traffic (mobile-heavy, iOS-heavy). Each location is anchored on a
university /16 — among the more stably geolocated public ranges — that resolves
~95% consistently to its region. The analytics tracker geolocates the *full* IP,
so a location surfaces as varied nearby cities/neighbourhoods and the odd
outlier; that spread is expected (and a
fair picture of free-GeoIP accuracy) — the region and timezone are what we
control. The abstract device keys are the producer's vocabulary; the journey
consumer maps them to concrete browser profiles (customer_journey/devices.py).

IP generation is the producer's job: it hands each visitor a distinct address so
the analytics tracker counts a distinct visitor (its fingerprint keys on the full
IP). Reusing an address to model a *returning* visitor is a deliberate, separate
act — see the recurrent flow in IdentityPool — never an accident of a small
address space.
"""

import random
from dataclasses import dataclass

from src.external_flows.contracts import VisitorEnvelope

# ~65k usable hosts per /16 make guest-IP collisions vanishingly rare and give a
# `taken`-set allocator ample room to guarantee uniqueness.
_IP_MINT_ATTEMPTS = 1000


@dataclass(frozen=True, slots=True)
class Location:
    city: str
    timezone: str
    # University /16 ("a.b"); the last two octets are minted per visitor. Each
    # prefix is verified to resolve ≥95% consistently to this region in the
    # shipped DB-IP City Lite database (the tracker geolocates the full IP) — don't
    # "correct" one to its real-world owner without re-checking that DB, whose
    # free tier disagrees with allocation in places. The region is what we pin;
    # the exact city may vary to a neighbour.
    prefix: str


US_LOCATIONS: tuple[Location, ...] = (
    Location("New York", "America/New_York", "128.59"),  # Columbia
    Location("Boston", "America/New_York", "128.197"),  # Boston Univ.
    Location("Philadelphia", "America/New_York", "130.91"),  # UPenn
    Location("Atlanta", "America/New_York", "130.207"),  # Georgia Tech
    Location("Miami", "America/New_York", "131.94"),  # FIU
    Location("Columbus", "America/New_York", "128.146"),  # Ohio State
    Location("East Lansing", "America/Detroit", "35.8"),  # Michigan State
    Location("Chicago", "America/Chicago", "128.135"),  # U. Chicago
    Location("Austin", "America/Chicago", "128.83"),  # UT Austin
    Location("Minneapolis", "America/Chicago", "128.101"),  # U. Minnesota
    Location("Boulder", "America/Denver", "128.138"),  # CU Boulder
    Location("Salt Lake City", "America/Denver", "155.98"),  # U. Utah
    Location("Tempe", "America/Phoenix", "129.219"),  # Arizona State
    Location("Los Angeles", "America/Los_Angeles", "128.97"),  # UCLA
    Location("Berkeley", "America/Los_Angeles", "128.32"),  # UC Berkeley
    Location("Seattle", "America/Los_Angeles", "128.95"),  # U. Washington
)

# Abstract device keys, weighted like US e-commerce traffic (weights need not
# sum to 1, cf. JOURNEYS in customer_journey/transitions.py).
DEVICE_POOL: dict[str, float] = {
    "iphone": 0.26,
    "iphone_large": 0.07,
    "android_phone": 0.10,
    "android_phone_samsung": 0.09,
    "ipad": 0.05,
    "desktop_chrome_win": 0.20,
    "desktop_chrome_mac": 0.12,
    "desktop_firefox_win": 0.08,
}


def _mint_ip(prefix: str, rng: random.Random, taken: set[str] | None) -> str:
    """A fresh host in the location's /16, avoiding any address already in `taken`.

    Falls back to a possibly-duplicate address only if the space is effectively
    exhausted (~65k hosts) — a guard against hanging, not an expected path.
    """
    for _ in range(_IP_MINT_ATTEMPTS):
        ip = f"{prefix}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
        if not taken or ip not in taken:
            return ip
    return ip


def mint_envelope(rng: random.Random, taken: set[str] | None = None) -> VisitorEnvelope:
    """One visitor's envelope: weighted device, uniform location, distinct host IP.

    Pass the set of already-issued IPs as `taken` to guarantee a brand-new
    address (the guest flow); omit it for a standalone draw.
    """
    device = rng.choices(list(DEVICE_POOL), weights=list(DEVICE_POOL.values()), k=1)[0]
    location = rng.choice(US_LOCATIONS)
    return VisitorEnvelope(
        device=device,
        ip=_mint_ip(location.prefix, rng, taken),
        city=location.city,
        timezone=location.timezone,
    )
