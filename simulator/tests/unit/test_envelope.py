"""The visitor-envelope mint: deterministic, region-anchored, and unique."""

import random

import pytest

from src.external_flows.customer_arrivals.envelope import (
    BROWSER_LOCALES,
    DEVICE_POOL,
    LOCATIONS,
    mint_envelope,
    pick_location,
)

MARKETS = sorted(LOCATIONS)


def mint(rng, taken=None, country="US"):
    """Draw a location in `country` and mint an envelope for someone there."""
    return mint_envelope(
        rng,
        taken,
        location=pick_location(rng, country),
        locale=BROWSER_LOCALES[country],
    )


def test_mint_is_deterministic_for_a_seed():
    assert mint(random.Random(42)) == mint(random.Random(42))


@pytest.mark.parametrize("country", MARKETS)
def test_ip_timezone_and_locale_come_from_the_picked_location(country):
    for seed in range(50):
        envelope = mint(random.Random(seed), country=country)
        location = next(loc for loc in LOCATIONS[country] if loc.city == envelope.city)
        octets = envelope.ip.split(".")
        assert ".".join(octets[:2]) == location.prefix  # host lives in the /16
        assert 1 <= int(octets[3]) <= 254
        assert envelope.timezone == location.timezone
        assert envelope.locale == BROWSER_LOCALES[country]


@pytest.mark.parametrize("country", MARKETS)
def test_every_device_and_location_is_reachable(country):
    rng = random.Random(0)
    minted = [mint(rng, country=country) for _ in range(2000)]
    assert {e.device for e in minted} == set(DEVICE_POOL)
    assert {e.city for e in minted} == {loc.city for loc in LOCATIONS[country]}


def test_the_locale_follows_the_person_not_the_place():
    """A Canadian browsing from a US city still reports en-CA — locale is a
    device setting, not a property of where they happen to be standing."""
    rng = random.Random(1)

    envelope = mint_envelope(
        rng, location=pick_location(rng, "US"), locale=BROWSER_LOCALES["CA"]
    )

    assert envelope.city in {loc.city for loc in LOCATIONS["US"]}
    assert envelope.locale == "en-CA"


@pytest.mark.parametrize("country", MARKETS)
def test_city_labels_are_unique_within_a_market(country):
    """Locations are resolved by city label; a duplicate would silently point at
    the wrong /16 and put the visitor in the wrong place."""
    cities = [loc.city for loc in LOCATIONS[country]]
    assert sorted(set(cities)) == sorted(cities)


@pytest.mark.parametrize("country", MARKETS)
def test_every_location_carries_a_region_and_postcode_prefix(country):
    """Both feed the checkout form. An empty one fails validation on the page,
    not here, where it would be obvious."""
    for location in LOCATIONS[country]:
        assert location.region, location
        assert location.postcode_prefix, location


def test_every_market_has_a_browser_locale():
    """Adding a location catalogue without its locale is a KeyError on the first
    arrival of that market, which is a long way from where the mistake was made."""
    assert set(BROWSER_LOCALES) == set(LOCATIONS)


def test_an_unknown_market_is_rejected():
    with pytest.raises(ValueError, match="no locations for market"):
        pick_location(random.Random(0), "ZZ")


def test_taken_set_guarantees_unique_ips():
    rng = random.Random(7)
    taken: set[str] = set()
    ips = []
    for _ in range(3000):
        ip = mint(rng, taken).ip
        taken.add(ip)
        ips.append(ip)
    assert len(set(ips)) == len(ips)  # every guest address is distinct
