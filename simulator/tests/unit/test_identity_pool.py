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


def test_the_visitor_arrives_from_inside_their_own_market():
    """A Canadian buyer on a US address would put the tracker's geography and the
    order's billing country permanently at odds — an artefact that looks exactly
    like a real cross-border signal."""
    pool = IdentityPool(rng=random.Random(5))

    for _ in range(300):
        identity = pool.pick()
        home = {loc.city for loc in LOCATIONS[identity.profile.country]}
        assert identity.visitor.city in home


def test_an_unknown_market_is_rejected_at_construction():
    """Boot-time, not on the first arrival — a typo in MARKET_MIX should not wait
    for traffic to surface."""
    with pytest.raises(ValueError, match="unknown market"):
        IdentityPool(rng=random.Random(1), markets={"XX": 1.0})


def test_a_mix_with_no_weight_is_rejected():
    with pytest.raises(ValueError, match="positive total weight"):
        IdentityPool(rng=random.Random(1), markets={"US": 0.0})
