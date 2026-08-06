"""What a million tokens costs, and what one run therefore did.

The one place this repository states a price. It lives with the employees rather
than with anything that displays them, because **the agent is what knows which
model it ran**: a portal, a report or a terminal should be handed the figure, not
left to work it out from a name and a table of its own. Two tables always
disagree eventually, and the day they do neither is obviously wrong.

**A model absent from `RATES` is unpriced, deliberately.** Only rates checked
against a provider's published card belong here. A figure this repository
invented is a figure it could publish wrong, and it has retracted one for less —
so `estimate` returns nothing rather than guessing, and every consumer shows the
token counts with no price.

**What this computes is not what a loop was billed.** Some loops report a real
charge and it travels as `Usage.cost`; that is a receipt. This is tokens
multiplied by a number somebody transcribed on a date, and it reaches an envelope
under its own name so the two can never be mistaken for each other.
"""

from dataclasses import dataclass

AS_OF = "2026-08-05"
"""When these rates were last checked. A rate card without a date cannot be
audited, and a stale price is worse than none: it is wrong and confident."""

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Rate:
    """USD per million tokens, as a provider publishes them.

    `cached_input` prices the part of `input` that was served from cache — a
    **subset** of it, never an addition. Charging both and adding them counts the
    cached share twice, and this stack resends a long prompt on every turn: a
    real run sent 10 303 tokens of which 6 942 were cached, where the naive sum
    overstates the cost by two thirds.
    """

    input: float
    cached_input: float
    output: float


RATES: dict[str, Rate] = {
    "gpt-5.6-sol": Rate(input=5.00, cached_input=0.50, output=30.00),
    "gpt-5.6-terra": Rate(input=2.00, cached_input=0.20, output=12.00),
    "gpt-5.6-luna": Rate(input=0.20, cached_input=0.02, output=1.20),
}
"""Keyed by the model name as the deployment names it — `AGENT_MODEL_NAME`, the
same string that reaches the provider and lands in the record.

Read off the published card after the 30 July 2026 cut, which moved terra and
luna and left sol alone. Cached input is a tenth of input across all three,
which is the provider's stated rule rather than three coincidences — and luna's
figures were already here from an independent reading, so the source agreeing
with them is what makes the other two trustworthy rather than merely plausible.

**A model absent from this table is unpriced, and that is a working state.** The
rule is that a rate is transcribed from a published card or it is not here at
all; the alternative is a number nobody can audit, on every run, in every
report, until a total fails to add up."""

CACHE_WRITE_MULTIPLIER = 1.25
"""What the provider charges to *place* a prompt in the cache, against the
uncached rate — noted because `estimate` does **not** model it.

The first turn of a run pays it and later turns do not, so an estimate is a
little low on a short investigation and negligibly so on a long one. Modelling
it would need the number of cache writes, which no loop reports. Named here so
the gap is a known bound rather than a surprise."""


def estimate(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float | None:
    """What this run would cost at the published rate, or nothing.

    `None` for a model nobody has priced, which is the honest answer and the
    common one. Cached tokens are subtracted from the fresh ones rather than
    added beside them — see `Rate`.
    """
    rate = RATES.get(model)
    if rate is None:
        return None

    sent = max(float(input_tokens), 0.0)
    cached = min(max(float(cache_read_tokens), 0.0), sent)
    billed = (
        (sent - cached) * rate.input
        + cached * rate.cached_input
        + max(float(output_tokens), 0.0) * rate.output
    )
    return round(billed / PER_MILLION, 4)
