import random

from src.external_flows.customer_arrivals.identity_pool import IdentityPool


def test_pick_mints_new_when_returning_ratio_zero():
    pool = IdentityPool(rng=random.Random(1), returning_ratio=0.0)
    customers = [pool.pick() for _ in range(5)]
    assert pool.size == 5
    assert len({c.email for c in customers}) == 5


def test_pick_reuses_when_returning_ratio_one():
    pool = IdentityPool(rng=random.Random(1), returning_ratio=1.0)
    first = pool.pick()  # pool is empty → must mint a new identity
    assert pool.size == 1
    again = [pool.pick() for _ in range(5)]
    assert pool.size == 1  # every subsequent pick is a returning customer
    assert all(c.email == first.email for c in again)


def test_pick_is_deterministic_for_a_seed():
    a = IdentityPool(rng=random.Random(42), returning_ratio=0.0).pick()
    b = IdentityPool(rng=random.Random(42), returning_ratio=0.0).pick()
    assert a == b


def test_pool_is_bounded_by_max_size():
    pool = IdentityPool(rng=random.Random(3), returning_ratio=0.0, max_size=10)
    for _ in range(50):
        pool.pick()
    assert pool.size == 10
