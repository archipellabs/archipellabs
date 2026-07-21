import random

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
