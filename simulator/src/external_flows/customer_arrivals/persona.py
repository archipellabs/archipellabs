"""Customer profile generation, backed by a single seeded Faker.

A profile is built *around a location*: the city, region and postcode come from
the catalogue, not from Faker, so the address is plausible for the place it
claims and passes the shop's own validation. Only the parts that are genuinely
arbitrary — name, street, email — are invented.
"""

import random

from faker import Faker

from src.external_flows.contracts import CustomerProfile
from src.external_flows.customer_arrivals.envelope import Location, pick_location

# Faker locales, one per market. Kept in step with the location catalogues
# (envelope.LOCATIONS): a market with no locations has no customers, and a market
# with no locale would be minted with the wrong names and street formats.
# Quebec personas are minted en_CA like the rest of Canada — fr_CA waits for the
# storefront to actually be bilingual.
FAKER_LOCALES: dict[str, str] = {
    "US": "en_US",
    "CA": "en_CA",
}

# Canada Post never uses D, F, I, O, Q or U in a postal code.
_CA_POSTCODE_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"


class PersonaFactory:
    """Mints customer profiles from one Faker, seeded once.

    Reused across a run (e.g. by IdentityPool): a single Faker called in sequence
    is deterministic for a given seed, with no per-profile re-seeding.
    """

    def __init__(self, country: str = "US", seed: int | None = None) -> None:
        if country not in FAKER_LOCALES:
            raise ValueError(
                f"no persona locale for market {country!r}; known: {sorted(FAKER_LOCALES)}"
            )
        self._country = country
        self._faker = Faker(FAKER_LOCALES[country])
        if seed is not None:
            self._faker.seed_instance(seed)

    def make(self, location: Location) -> CustomerProfile:
        """One customer who lives at `location`."""
        fake = self._faker
        first = fake.first_name()
        last = fake.last_name()
        email_local = f"{first}.{last}.{fake.random_number(digits=6)}".lower()
        return CustomerProfile(
            firstname=first,
            lastname=last,
            email=f"{email_local}@example.com",
            address1=fake.street_address(),
            city=location.city,
            postcode=self._postcode(location),
            state=location.region,
            phone=fake.phone_number(),
            country=self._country,
        )

    def _postcode(self, location: Location) -> str:
        """A postcode in `location`, in the format PrestaShop validates against.

        `ps_country.zip_code_format` is "NNNNN" for the US and "LNL NLN" for
        Canada — and Faker's own en_CA postcode drops that mandatory space about
        half the time, which fails address validation at checkout with no error
        anywhere upstream.
        """
        fake = self._faker
        if self._country == "CA":
            tail = (
                fake.numerify("#")
                + fake.lexify("?", letters=_CA_POSTCODE_LETTERS)
                + fake.numerify("#")
            )
            return f"{location.postcode_prefix} {tail}"
        return f"{location.postcode_prefix}{fake.numerify('##')}"


def generate_customer_profile(
    country: str = "US", seed: int | None = None
) -> CustomerProfile:
    """One-off convenience for callers without a factory (tests, standalone runs).

    Picks the customer's home location too, so the caller only has to name a
    market. Deterministic when `seed` is given.
    """
    rng = random.Random(seed)
    return PersonaFactory(country=country, seed=seed).make(pick_location(rng, country))
