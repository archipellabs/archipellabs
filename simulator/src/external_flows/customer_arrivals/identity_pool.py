"""In-memory pool of customer identities for the arrivals flow.

Held by the customer-arrivals scheduler lifespan, so it is shared across ticks
(POOL scope). On each arrival it decides, with the injected run RNG, whether to
reuse a returning customer or mint a brand-new one (via a seeded PersonaFactory)
— the simulator's notion of loyalty. Identities are forgotten on restart (v1
keeps the pool purely in memory).
"""

import random
from collections import deque

from src.external_flows.contracts import CustomerProfile
from src.external_flows.customer_arrivals.persona import PersonaFactory


class IdentityPool:
    def __init__(
        self,
        *,
        rng: random.Random,
        country: str = "US",
        returning_ratio: float = 0.3,
        max_size: int = 500,
    ) -> None:
        self._rng = rng
        self._returning_ratio = returning_ratio
        self._personas = PersonaFactory(country=country, seed=rng.randint(0, 2**31 - 1))
        self._known: deque[CustomerProfile] = deque(maxlen=max_size)

    def pick(self) -> CustomerProfile:
        """A returning customer (probability `returning_ratio`, once the pool is
        non-empty) or a freshly minted and remembered one."""
        if self._known and self._rng.random() < self._returning_ratio:
            return self._rng.choice(self._known)
        profile = self._personas.make()
        self._known.append(profile)
        return profile

    @property
    def size(self) -> int:
        return len(self._known)
