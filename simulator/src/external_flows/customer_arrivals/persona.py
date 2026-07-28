"""Customer profile generation, backed by a single seeded Faker."""

from faker import Faker

from src.external_flows.contracts import CustomerProfile


def _locale_for(country: str) -> str:
    return {"US": "en_US", "CA": "en_CA", "FR": "fr_FR", "GB": "en_GB"}.get(
        country, "en_US"
    )


def _canadian_postcode(raw: str) -> str:
    """Faker's en_CA drops the space about half the time ("J1E7V7").

    PrestaShop validates against `ps_country.zip_code_format`, which is
    "LNL NLN" for Canada — so the unspaced half fails address validation and the
    journey dies at checkout step 2 with no error anywhere upstream. Exactly the
    silent-at-the-infra-layer failure this simulator exists to produce, which is
    why it must not happen by accident.
    """
    compact = raw.replace(" ", "").upper()
    if len(compact) != 6:
        return raw
    return f"{compact[:3]} {compact[3:]}"


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
        postcode = fake.postcode()
        if self._country == "CA":
            postcode = _canadian_postcode(postcode)
        return CustomerProfile(
            firstname=first,
            lastname=last,
            email=f"{email_local}@example.com",
            address1=fake.street_address(),
            city=fake.city(),
            postcode=postcode,
            phone=fake.phone_number(),
            country=self._country,
        )


def generate_customer_profile(
    country: str = "US", seed: int | None = None
) -> CustomerProfile:
    """One-off convenience for callers without a factory (tests, standalone runs)."""
    return PersonaFactory(country=country, seed=seed).make()
