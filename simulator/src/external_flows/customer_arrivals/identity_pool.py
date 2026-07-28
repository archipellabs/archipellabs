"""Mints a fresh visitor identity for each arrival.

Held by the customer-arrivals scheduler lifespan (POOL scope) so its seeded
persona factories and issued-IP set persist across ticks. Every arrival is a
brand-new visitor: a market drawn from the shop's mix, then a random profile from
that market plus a fresh, guaranteed-unique envelope (device + IP + locality).
Because each IP is distinct, each visit is a distinct visitor to the analytics
tracker.

The market mix is the shop's knob — which countries it sells to and how traffic
splits between them — so it is config, unlike the location catalogues and rate
curves it draws on. One Faker per market, seeded once, keeps a run reproducible.

Modelling *returning* visitors — reusing an identity/envelope so a visitor is
recognized across visits — is a deliberately separate, more involved "revisit"
mechanic left for a later stage. There is no reuse here yet; the persisted
issued-IP set exists only to keep fresh addresses unique.
"""

import random
from collections.abc import Mapping
from dataclasses import dataclass

from src.external_flows.contracts import CustomerProfile, VisitorEnvelope
from src.external_flows.customer_arrivals.envelope import LOCATIONS, mint_envelope
from src.external_flows.customer_arrivals.persona import PersonaFactory

DEFAULT_MARKET_MIX: dict[str, float] = {"US": 0.75, "CA": 0.25}
"""Traffic split for a North America-scoped shop. Weights are relative, not
percentages (cf. DEVICE_POOL), so they need not sum to 1."""


@dataclass(frozen=True, slots=True)
class Identity:
    profile: CustomerProfile
    visitor: VisitorEnvelope


class IdentityPool:
    def __init__(
        self, *, rng: random.Random, markets: Mapping[str, float] | None = None
    ) -> None:
        self._rng = rng
        mix = dict(markets) if markets else dict(DEFAULT_MARKET_MIX)

        # Validate the whole mix at construction: a typo in the market config is
        # a boot-time failure, not a surprise on the first arrival of the night.
        unknown = sorted(set(mix) - set(LOCATIONS))
        if unknown:
            raise ValueError(f"unknown market(s) {unknown}; known: {sorted(LOCATIONS)}")
        if any(weight < 0 for weight in mix.values()) or sum(mix.values()) <= 0:
            raise ValueError(f"market mix needs a positive total weight, got {mix}")

        self._markets = list(mix)
        self._weights = list(mix.values())
        self._personas = {
            country: PersonaFactory(country=country, seed=rng.randint(0, 2**31 - 1))
            for country in self._markets
        }
        # Every IP ever issued, so each visitor's address stays globally unique.
        # Grows with the run; fine at v1 volumes (each /16 holds ~65k addresses).
        self._issued_ips: set[str] = set()

    def pick(self) -> Identity:
        """Mint the next arrival's identity: a new customer on a unique envelope."""
        country = self._rng.choices(self._markets, weights=self._weights, k=1)[0]
        envelope = mint_envelope(self._rng, self._issued_ips, country=country)
        self._issued_ips.add(envelope.ip)
        return Identity(profile=self._personas[country].make(), visitor=envelope)
