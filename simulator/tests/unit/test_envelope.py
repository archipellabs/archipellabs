"""The visitor-envelope mint: deterministic, region-anchored, and unique."""

import random

import pytest

from src.external_flows.customer_arrivals.envelope import (
    BROWSER_LOCALES,
    DEVICE_POOL,
    LOCATIONS,
    mint_envelope,
)

MARKETS = sorted(LOCATIONS)


def test_mint_is_deterministic_for_a_seed():
    assert mint_envelope(random.Random(42)) == mint_envelope(random.Random(42))


@pytest.mark.parametrize("country", MARKETS)
def test_ip_timezone_and_locale_come_from_the_picked_location(country):
    for seed in range(50):
        envelope = mint_envelope(random.Random(seed), country=country)
        location = next(loc for loc in LOCATIONS[country] if loc.city == envelope.city)
        octets = envelope.ip.split(".")
        assert ".".join(octets[:2]) == location.prefix  # host lives in the /16
        assert 1 <= int(octets[3]) <= 254
        assert envelope.timezone == location.timezone
        assert envelope.locale == BROWSER_LOCALES[country]


@pytest.mark.parametrize("country", MARKETS)
def test_every_device_and_location_is_reachable(country):
    rng = random.Random(0)
    minted = [mint_envelope(rng, country=country) for _ in range(2000)]
    assert {e.device for e in minted} == set(DEVICE_POOL)
    assert {e.city for e in minted} == {loc.city for loc in LOCATIONS[country]}


@pytest.mark.parametrize("country", MARKETS)
def test_city_labels_are_unique_within_a_market(country):
    """Locations are resolved by city label; a duplicate would silently point at
    the wrong /16 and put the visitor in the wrong place."""
    cities = [loc.city for loc in LOCATIONS[country]]
    assert sorted(set(cities)) == sorted(cities)


def test_every_market_has_a_browser_locale():
    """Adding a location catalogue without its locale is a KeyError on the first
    arrival of that market, which is a long way from where the mistake was made."""
    assert set(BROWSER_LOCALES) == set(LOCATIONS)


def test_an_unknown_market_is_rejected():
    with pytest.raises(ValueError, match="no locations for market"):
        mint_envelope(random.Random(0), country="ZZ")


def test_taken_set_guarantees_unique_ips():
    rng = random.Random(7)
    taken: set[str] = set()
    ips = []
    for _ in range(3000):
        ip = mint_envelope(rng, taken).ip
        taken.add(ip)
        ips.append(ip)
    assert len(set(ips)) == len(ips)  # every guest address is distinct
