"""The visitor-envelope mint: deterministic, region-anchored, and unique."""

import random

from src.external_flows.customer_arrivals.envelope import (
    DEVICE_POOL,
    US_LOCATIONS,
    mint_envelope,
)


def test_mint_is_deterministic_for_a_seed():
    assert mint_envelope(random.Random(42)) == mint_envelope(random.Random(42))


def test_ip_and_timezone_come_from_the_picked_location():
    for seed in range(50):
        envelope = mint_envelope(random.Random(seed))
        location = next(loc for loc in US_LOCATIONS if loc.city == envelope.city)
        octets = envelope.ip.split(".")
        assert ".".join(octets[:2]) == location.prefix  # host lives in the /16
        assert 1 <= int(octets[3]) <= 254
        assert envelope.timezone == location.timezone
        assert envelope.locale == "en-US"


def test_every_device_and_location_is_reachable():
    rng = random.Random(0)
    minted = [mint_envelope(rng) for _ in range(2000)]
    assert {e.device for e in minted} == set(DEVICE_POOL)
    assert {e.city for e in minted} == {loc.city for loc in US_LOCATIONS}


def test_taken_set_guarantees_unique_ips():
    rng = random.Random(7)
    taken: set[str] = set()
    ips = []
    for _ in range(3000):
        ip = mint_envelope(rng, taken).ip
        taken.add(ip)
        ips.append(ip)
    assert len(set(ips)) == len(ips)  # every guest address is distinct
