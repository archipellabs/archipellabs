import random
from collections import Counter

import pytest

from src.external_flows.customer_arrivals.envelope import LOCATIONS
from src.external_flows.customer_arrivals.identity_pool import IdentityPool


def test_each_pick_is_a_new_customer():
    pool = IdentityPool(rng=random.Random(1))
    identities = [pool.pick() for _ in range(50)]
    assert len({i.profile.email for i in identities}) == 50


def test_each_pick_gets_a_unique_ip():
    pool = IdentityPool(rng=random.Random(1))
    ips = [pool.pick().visitor.ip for _ in range(500)]
    assert len(set(ips)) == len(ips)


def test_pick_is_deterministic_for_a_seed():
    a = IdentityPool(rng=random.Random(42)).pick()
    b = IdentityPool(rng=random.Random(42)).pick()
    assert a == b


def test_the_market_mix_shapes_the_country_split():
    pool = IdentityPool(rng=random.Random(3), markets={"US": 0.75, "CA": 0.25})

    countries = Counter(pool.pick().profile.country for _ in range(2000))

    assert set(countries) == {"US", "CA"}
    assert 0.21 < countries["CA"] / 2000 < 0.29


def test_a_single_market_draws_only_that_market():
    """The lever for isolating one market's traffic — and for the control run of
    an experiment that breaks the other one."""
    pool = IdentityPool(rng=random.Random(3), markets={"CA": 1})

    assert {pool.pick().profile.country for _ in range(200)} == {"CA"}


def test_most_visitors_browse_from_the_town_they_live_in():
    """Deliberately not all of them. Travellers, VPNs and gift shipping mean IP
    geography and billing address disagree for a slice of any real population; if
    they matched perfectly the two signals would be interchangeable, and analysis
    resting on one would look sound for reasons true only in the simulation."""
    pool = IdentityPool(rng=random.Random(5))

    identities = [pool.pick() for _ in range(3000)]
    at_home = sum(1 for i in identities if i.visitor.city == i.profile.city)

    assert 0.76 < at_home / len(identities) < 0.84  # AT_HOME_PROBABILITY = 0.80


def test_visitors_who_are_away_are_usually_still_in_their_own_country():
    """Leaving the country is the rarer trip, so cross-border traffic stays a
    thin slice instead of distorting each market's geography."""
    pool = IdentityPool(rng=random.Random(11))

    away = [
        i
        for i in (pool.pick() for _ in range(4000))
        if i.visitor.city != i.profile.city
    ]
    domestic = sum(
        1
        for i in away
        if i.visitor.city in {loc.city for loc in LOCATIONS[i.profile.country]}
    )

    assert away, "nobody travelled; the away path never ran"
    assert 0.74 < domestic / len(away) < 0.86  # DOMESTIC_WHEN_AWAY = 0.80


def test_a_visitor_always_lands_in_a_real_place():
    """Whether home or away, the envelope's city is one we have a /16 for — an
    invented city would geolocate somewhere unrelated."""
    pool = IdentityPool(rng=random.Random(5))
    known = {loc.city for locations in LOCATIONS.values() for loc in locations}

    assert {pool.pick().visitor.city for _ in range(500)} <= known


def test_the_browser_locale_follows_the_customers_market():
    """Not the market they are browsing from: a Canadian in Chicago is still a
    Canadian, and the storefront should see en-CA."""
    pool = IdentityPool(rng=random.Random(9), markets={"CA": 1})

    assert {pool.pick().visitor.locale for _ in range(200)} == {"en-CA"}


def test_an_unknown_market_is_rejected_at_construction():
    """Boot-time, not on the first arrival — a typo in MARKET_MIX should not wait
    for traffic to surface."""
    with pytest.raises(ValueError, match="unknown market"):
        IdentityPool(rng=random.Random(1), markets={"XX": 1.0})


def test_a_mix_with_no_weight_is_rejected():
    with pytest.raises(ValueError, match="positive total weight"):
        IdentityPool(rng=random.Random(1), markets={"US": 0.0})
