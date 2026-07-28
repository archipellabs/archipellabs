"""Personas have to satisfy the shop's own validation.

A profile the storefront rejects does not raise anywhere — the journey simply
stops filling the address form and the customer abandons, which reads in the
analytics as an ordinary drop-off. These are the invariants that keep a
generation bug from looking like a business signal.
"""

import random
import re

import pytest

from src.external_flows.customer_arrivals.envelope import LOCATIONS, pick_location
from src.external_flows.customer_arrivals.persona import (
    FAKER_LOCALES,
    PersonaFactory,
    generate_customer_profile,
)

# Verbatim from ps_country.zip_code_format on the running shop: N is a digit,
# L a letter, and the space in the Canadian format is mandatory.
POSTCODE_PATTERNS = {
    "US": re.compile(r"^\d{5}$"),  # NNNNN
    "CA": re.compile(r"^[A-Z]\d[A-Z] \d[A-Z]\d$"),  # LNL NLN
}

MARKETS = sorted(LOCATIONS)


@pytest.mark.parametrize("country", MARKETS)
def test_postcodes_match_the_shops_zip_code_format(country):
    """Faker's own en_CA drops the space about half the time, which PrestaShop
    rejects at checkout step 2 with no error upstream."""
    factory = PersonaFactory(country=country, seed=11)
    rng = random.Random(3)
    pattern = POSTCODE_PATTERNS[country]

    offenders = [
        profile.postcode
        for profile in (factory.make(pick_location(rng, country)) for _ in range(500))
        if not pattern.match(profile.postcode)
    ]

    assert offenders == []


@pytest.mark.parametrize("country", MARKETS)
def test_the_address_belongs_to_the_place_it_claims(country):
    """City, region and postcode all come from one location, so an address is
    internally coherent rather than three independent draws."""
    factory = PersonaFactory(country=country, seed=7)

    for location in LOCATIONS[country]:
        profile = factory.make(location)
        assert profile.city == location.city
        assert profile.state == location.region
        assert profile.postcode.startswith(location.postcode_prefix)
        assert profile.country == country


def test_every_market_has_a_persona_locale():
    """A market with locations but no locale would mint US names and streets for
    customers the shop believes are somewhere else."""
    assert set(FAKER_LOCALES) == set(LOCATIONS)


def test_an_unknown_market_is_rejected():
    with pytest.raises(ValueError, match="no persona locale for market"):
        PersonaFactory(country="ZZ")


def test_personas_are_distinct_within_a_market():
    factory = PersonaFactory(country="CA", seed=5)
    location = LOCATIONS["CA"][0]
    assert len({factory.make(location).email for _ in range(200)}) == 200


@pytest.mark.parametrize("country", MARKETS)
def test_the_standalone_helper_picks_a_home_for_you(country):
    profile = generate_customer_profile(country=country, seed=4)

    assert profile.city in {loc.city for loc in LOCATIONS[country]}
    assert POSTCODE_PATTERNS[country].match(profile.postcode)
