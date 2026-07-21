"""Mints a fresh visitor identity for each arrival.

Held by the customer-arrivals scheduler lifespan (POOL scope) so its seeded
persona factory and issued-IP set persist across ticks. Every arrival is a
brand-new visitor: a random profile plus a fresh, guaranteed-unique envelope
(device + IP + locality). Because each IP is distinct, each visit is a distinct
visitor to the analytics tracker.

Modelling *returning* visitors — reusing an identity/envelope so a visitor is
recognized across visits — is a deliberately separate, more involved "revisit"
mechanic left for a later stage. There is no reuse here yet; the persisted
issued-IP set exists only to keep fresh addresses unique.
"""

import random
from dataclasses import dataclass

from src.external_flows.contracts import CustomerProfile, VisitorEnvelope
from src.external_flows.customer_arrivals.envelope import mint_envelope
from src.external_flows.customer_arrivals.persona import PersonaFactory


@dataclass(frozen=True, slots=True)
class Identity:
    profile: CustomerProfile
    visitor: VisitorEnvelope


class IdentityPool:
    def __init__(self, *, rng: random.Random, country: str = "US") -> None:
        self._rng = rng
        self._personas = PersonaFactory(country=country, seed=rng.randint(0, 2**31 - 1))
        # Every IP ever issued, so each visitor's address stays globally unique.
        # Grows with the run; fine at v1 volumes (the /16 pool holds ~1M addresses).
        self._issued_ips: set[str] = set()

    def pick(self) -> Identity:
        """Mint the next arrival's identity: a new customer on a unique envelope."""
        envelope = mint_envelope(self._rng, self._issued_ips)
        self._issued_ips.add(envelope.ip)
        return Identity(profile=self._personas.make(), visitor=envelope)
