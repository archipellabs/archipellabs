"""Mints a fresh visitor identity for each arrival.

Held by the customer-arrivals scheduler lifespan (POOL scope) so its seeded
persona factories and issued-IP set persist across ticks. Every arrival is a
brand-new visitor: a market drawn from the shop's mix, a home town inside it,
then a profile that lives there and an envelope that says where they are
browsing from. Because each IP is distinct, each visit is a distinct visitor to
the analytics tracker.

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
from src.external_flows.customer_arrivals.envelope import (
    BROWSER_LOCALES,
    LOCATIONS,
    Location,
    mint_envelope,
    pick_location,
)
from src.external_flows.customer_arrivals.persona import PersonaFactory

DEFAULT_MARKET_MIX: dict[str, float] = {"US": 0.75, "CA": 0.25}
"""Traffic split for a North America-scoped shop. Weights are relative, not
percentages (cf. DEVICE_POOL), so they need not sum to 1."""

AT_HOME_PROBABILITY = 0.80
"""How often a visitor browses from the town they live in.

Not 1.0 on purpose. Real traffic always carries people who are travelling, on a
VPN, or shipping to someone else, so IP geography and billing address disagree
for a slice of every population. Pinning them together would make the two
signals interchangeable — and then any analysis built on one would look
trustworthy for reasons that only hold in the simulation."""

DOMESTIC_WHEN_AWAY = 0.80
"""Of the visitors who are away, how many are still in their own country.
Leaving the country is the rarer case, so cross-border traffic stays a thin
slice rather than a distortion of the per-market geography."""


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

    def set_market_mix(self, mix: Mapping[str, float]) -> None:
        """Change the market weights in place, keeping every identity.

        A new pool would be simpler and wrong: the personas are seeded and the
        pool remembers which identities have been used, which is what makes a
        returning visitor look like one. Rebuilding it on a settings change would
        silently reset that, so only the weights move.
        """
        candidate = dict(mix)
        unknown = sorted(set(candidate) - set(LOCATIONS))
        if unknown:
            raise ValueError(f"unknown market(s) {unknown}; known: {sorted(LOCATIONS)}")
        if any(w < 0 for w in candidate.values()) or sum(candidate.values()) <= 0:
            raise ValueError(f"market mix needs a positive total weight, got {mix}")

        if candidate == dict(zip(self._markets, self._weights, strict=True)):
            return

        for country in candidate:
            if country not in self._personas:
                self._personas[country] = PersonaFactory(
                    country=country, seed=self._rng.randint(0, 2**31 - 1)
                )
        self._markets = list(candidate)
        self._weights = list(candidate.values())

    def pick(self) -> Identity:
        """Mint the next arrival's identity: a new customer on a unique envelope."""
        country = self._rng.choices(self._markets, weights=self._weights, k=1)[0]
        home = pick_location(self._rng, country)
        here = self._browsing_from(country, home)

        envelope = mint_envelope(
            self._rng,
            self._issued_ips,
            location=here,
            locale=BROWSER_LOCALES[country],
        )
        self._issued_ips.add(envelope.ip)
        return Identity(profile=self._personas[country].make(home), visitor=envelope)

    def _browsing_from(self, country: str, home: Location) -> Location:
        """Where this visitor physically is, usually but not always home.

        The away pool spans every known market, not just the ones the shop sells
        to: being somewhere is a fact about the person, not about the catalogue.
        """
        if self._rng.random() < AT_HOME_PROBABILITY:
            return home

        if self._rng.random() < DOMESTIC_WHEN_AWAY:
            elsewhere = [loc for loc in LOCATIONS[country] if loc != home]
        else:
            elsewhere = [
                loc
                for market, locations in LOCATIONS.items()
                if market != country
                for loc in locations
            ]
        return self._rng.choice(elsewhere) if elsewhere else home
