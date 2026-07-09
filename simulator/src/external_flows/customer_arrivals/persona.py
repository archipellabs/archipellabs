"""Customer profile generation, backed by a single seeded Faker."""

from faker import Faker

from src.external_flows.contracts import CustomerProfile


def _locale_for(country: str) -> str:
    return {"US": "en_US", "FR": "fr_FR", "GB": "en_GB"}.get(country, "en_US")


class PersonaFactory:
    """Mints customer profiles from one Faker, seeded once.

    Reused across a run (e.g. by IdentityPool): a single Faker called in sequence
    is deterministic for a given seed, with no per-profile re-seeding.
    """

    def __init__(self, country: str = "US", seed: int | None = None) -> None:
        self._country = country
        self._faker = Faker(_locale_for(country))
        if seed is not None:
            self._faker.seed_instance(seed)

    def make(self) -> CustomerProfile:
        fake = self._faker
        first = fake.first_name()
        last = fake.last_name()
        email_local = f"{first}.{last}.{fake.random_number(digits=6)}".lower()
        return CustomerProfile(
            firstname=first,
            lastname=last,
            email=f"{email_local}@example.com",
            address1=fake.street_address(),
            city=fake.city(),
            postcode=fake.postcode(),
            phone=fake.phone_number(),
            country=self._country,
        )


def generate_customer_profile(
    country: str = "US", seed: int | None = None
) -> CustomerProfile:
    """One-off convenience for callers without a factory (tests, standalone runs)."""
    return PersonaFactory(country=country, seed=seed).make()
