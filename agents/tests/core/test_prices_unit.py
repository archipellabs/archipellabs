"""The one place a price is stated, and the one arithmetic trap in it."""

from core import prices


def test_cached_input_is_a_subset_not_an_addition():
    """This stack resends a long prompt every turn, so most of what it "sends"
    was already cached. Charging the cached share on top of the fresh share
    counts it twice: on a real run — 10 303 sent of which 6 942 cached — the
    naive sum is $0.0034 against $0.0021, a 60% overstatement on every run."""
    correct = prices.estimate(
        "gpt-5.6-luna",
        input_tokens=10_303,
        output_tokens=1_036,
        cache_read_tokens=6_942,
    )
    rate = prices.RATES["gpt-5.6-luna"]
    naive = (
        10_303 * rate.input + 6_942 * rate.cached_input + 1_036 * rate.output
    ) / prices.PER_MILLION

    assert correct == 0.0021
    assert round(naive, 4) == 0.0034


def test_a_model_nobody_checked_is_unpriced_rather_than_free():
    """Only rates transcribed from a published card belong in the table, and a
    model outside it shows its tokens and no money. Unpriced is a working state,
    not a gap to paper over."""
    assert prices.estimate("nothing-like-a-model", input_tokens=1_000) is None
    assert prices.estimate("", input_tokens=1_000) is None


def test_every_model_the_portal_offers_is_priced():
    """The three the picker lists. A run whose cost silently vanishes is worse
    than one that is obviously unpriced, because nobody goes looking."""
    for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert prices.estimate(model, input_tokens=1_000, output_tokens=100)


def test_cached_input_is_a_tenth_of_input_across_the_family():
    """The provider's stated rule, not three coincidences — and the thing most
    easily got wrong when a rate is copied by hand."""
    for model, rate in prices.RATES.items():
        assert rate.cached_input == round(rate.input / 10, 4), model


def test_the_tiers_are_in_the_order_the_card_puts_them():
    """A transcription error that swapped two rows would price every sol run at
    a twenty-fifth of its cost, and nothing else would notice."""
    sol = prices.RATES["gpt-5.6-sol"]
    terra = prices.RATES["gpt-5.6-terra"]
    luna = prices.RATES["gpt-5.6-luna"]

    assert sol.input > terra.input > luna.input
    assert sol.output > terra.output > luna.output


def test_cached_can_never_exceed_what_was_sent():
    """A provider reporting more cached than input would otherwise price the
    difference at a negative rate."""
    assert prices.estimate(
        "gpt-5.6-luna", input_tokens=100, cache_read_tokens=1_000
    ) == round(100 * prices.RATES["gpt-5.6-luna"].cached_input / 1e6, 4)


def test_the_table_says_when_it_was_last_checked():
    """A rate card without a date cannot be audited, and a stale price is worse
    than none: it is wrong and confident."""
    assert prices.AS_OF
