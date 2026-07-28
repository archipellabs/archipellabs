"""Personas have to satisfy the shop's own validation.

A profile the storefront rejects does not raise anywhere — the journey simply
stops filling the address form and the customer abandons, which reads in the
analytics as an ordinary drop-off. These are the invariants that keep a
generation bug from looking like a business signal.
"""

import re

import pytest

from src.external_flows.customer_arrivals.persona import PersonaFactory

# Verbatim from ps_country.zip_code_format on the running shop: N is a digit,
# L a letter, and the space in the Canadian format is mandatory.
POSTCODE_PATTERNS = {
    "US": re.compile(r"^\d{5}$"),  # NNNNN
    "CA": re.compile(r"^[A-Z]\d[A-Z] \d[A-Z]\d$"),  # LNL NLN
}


@pytest.mark.parametrize("country", sorted(POSTCODE_PATTERNS))
def test_postcodes_match_the_shops_zip_code_format(country):
    """Faker's en_CA drops the space about half the time, which PrestaShop
    rejects at checkout step 2 with no error upstream."""
    factory = PersonaFactory(country=country, seed=11)
    pattern = POSTCODE_PATTERNS[country]

    offenders = [
        postcode
        for postcode in (factory.make().postcode for _ in range(500))
        if not pattern.match(postcode)
    ]

    assert offenders == []


@pytest.mark.parametrize("country", sorted(POSTCODE_PATTERNS))
def test_the_profile_carries_the_market_it_was_minted_for(country):
    assert PersonaFactory(country=country, seed=3).make().country == country


def test_personas_are_distinct_within_a_market():
    factory = PersonaFactory(country="CA", seed=5)
    assert len({factory.make().email for _ in range(200)}) == 200
