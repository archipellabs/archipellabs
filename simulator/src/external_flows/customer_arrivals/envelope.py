"""Visitor envelopes — which device, and from where, a simulated customer arrives.

Universal shape data, constants not config (like the rate curves in rate.py): a
fixed catalogue of locations per market and a device mix roughly shaped like
North American e-commerce traffic (mobile-heavy, iOS-heavy). Each location is
anchored on a university /16 — among the more stably geolocated public ranges —
that resolves ~95% consistently to its region. The analytics tracker geolocates
the *full* IP, so a location surfaces as varied nearby cities/neighbourhoods and
the odd outlier; that spread is expected (and a
fair picture of free-GeoIP accuracy) — the region and timezone are what we
control. The abstract device keys are the producer's vocabulary; the journey
consumer maps them to concrete browser profiles (customer_journey/devices.py).

*Which* markets arrive, and in what proportion, is a per-shop knob and lives with
the identity pool; this module only answers "where in that market".

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
    #
    # To re-check a candidate, sample hosts across the /16 against the database
    # the tracker actually reads (misc/DBIP-City.mmdb in the Matomo container)
    # rather than a public whois — the two disagree, and only the former decides
    # what the analytics report.
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

# The mix of provinces roughly tracks population (Ontario heaviest, then Quebec,
# BC and Alberta), the same way US_LOCATIONS leans east — locations are drawn
# uniformly, so the *composition* of the tuple is what shapes the geography.
# No two entries share a city label: callers resolve a location by city.
CA_LOCATIONS: tuple[Location, ...] = (
    Location("Toronto", "America/Toronto", "128.100"),  # U. Toronto
    Location("Ottawa", "America/Toronto", "137.122"),  # U. Ottawa
    Location("Waterloo", "America/Toronto", "129.97"),  # U. Waterloo
    Location("Hamilton", "America/Toronto", "130.113"),  # McMaster
    Location("Montreal", "America/Toronto", "132.206"),  # McGill
    Location("Quebec City", "America/Toronto", "132.203"),  # U. Laval
    Location("Vancouver", "America/Vancouver", "137.82"),  # UBC
    Location("Victoria", "America/Vancouver", "142.104"),  # U. Victoria
    Location("Calgary", "America/Edmonton", "136.159"),  # U. Calgary
    Location("Edmonton", "America/Edmonton", "129.128"),  # U. Alberta
    Location("Winnipeg", "America/Winnipeg", "130.179"),  # U. Manitoba
    Location("Halifax", "America/Halifax", "129.173"),  # Dalhousie
)

LOCATIONS: dict[str, tuple[Location, ...]] = {
    "US": US_LOCATIONS,
    "CA": CA_LOCATIONS,
}

# What the browser reports (BCP-47), as opposed to the Faker locale a persona is
# minted from (persona.py). Both derive from the market; neither format fits both.
BROWSER_LOCALES: dict[str, str] = {
    "US": "en-US",
    "CA": "en-CA",
}

# Abstract device keys, weighted like North American e-commerce traffic (weights
# need not sum to 1, cf. JOURNEYS in customer_journey/transitions.py). Shared
# across markets: the US and Canadian device mixes are close enough that a split
# would be invented precision.
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


def mint_envelope(
    rng: random.Random, taken: set[str] | None = None, *, country: str = "US"
) -> VisitorEnvelope:
    """One visitor's envelope: weighted device, uniform location, distinct host IP.

    Pass the set of already-issued IPs as `taken` to guarantee a brand-new
    address (the guest flow); omit it for a standalone draw. `country` selects
    the location catalogue — an unknown one is a wiring mistake, not a fallback.
    """
    try:
        locations = LOCATIONS[country]
    except KeyError:
        raise ValueError(
            f"no locations for market {country!r}; known: {sorted(LOCATIONS)}"
        ) from None

    device = rng.choices(list(DEVICE_POOL), weights=list(DEVICE_POOL.values()), k=1)[0]
    location = rng.choice(locations)
    return VisitorEnvelope(
        device=device,
        ip=_mint_ip(location.prefix, rng, taken),
        city=location.city,
        timezone=location.timezone,
        locale=BROWSER_LOCALES[country],
    )
