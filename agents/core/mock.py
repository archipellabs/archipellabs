"""An employee that costs nothing, so everything around one can be tested.

Every other loop in this package needs a model, a key and either a subprocess or
a network. That made the machinery *around* the loop — the envelope, the event
stream, the record, the bus mount, the page rendering it — testable only by
spending money and waiting minutes, which is why so much of it was first
exercised in production and found broken there.

This is the same interface with the loop taken out. It emits a fixed script of
steps, optionally spaced by a delay, and always answers the same thing.

**Always the same answer.** A mock that varied would be a second thing under
test: a failing assertion could not distinguish the code under test from the
double. The verdict below is a real one — the carrier incident this lab stages —
so a page rendering it shows something a reader would recognise rather than
`lorem ipsum`.
"""

import asyncio
import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field

from core.config import Config
from core.contract import Answer, Finding
from core.harness.base import Kind, Outcome, Step, Usage

ANSWER = Answer(
    detected="Canadian customers cannot complete checkout: they reach the "
    "delivery step and no shipping method is offered. US checkout is unaffected.",
    diagnosis="No carrier serves the zone Canada belongs to, so the shop has "
    "nothing to price and the delivery step renders empty.",
    root_cause="The carrier reference feed stopped carrying its Canadian rows, "
    "and the integration reconciled the shop to match.",
    remediation="Restore the Canadian rows in the carrier feed and re-run the "
    "import, then confirm a delivery option prices for a Canadian address.",
    findings=[
        Finding(fact="0 Canadian orders since 20:28, against 27 US orders in "
                "the same window.", source="shop — orders joined to addresses"),
        Finding(fact="The carrier feed holds US rows only.",
                source="ERP file drop — carriers.csv"),
    ],
    confidence="high",
)
"""The fixed verdict. Complete under the contract, so it exercises every field."""

USAGE = Usage(
    model_requests=4,
    input_tokens=10_303,
    output_tokens=1_036,
    reasoning_tokens=647,
    cache_read_tokens=6_942,
)
"""Non-zero on every counter, so an envelope's accounting is actually asserted.

Zeros would pass a test that never wrote the fields at all."""

SCRIPT: tuple[tuple[Kind, str], ...] = (
    (Kind.THINKING, "Checking whether Canadian customers are still arriving."),
    (Kind.COMMAND, "curl -s $SHOP_API_URL/orders?display=[id,id_address_delivery]"),
    (Kind.OUTPUT, "27 orders, none with a Canadian delivery address"),
    (Kind.TOOL, "shop_get"),
    (Kind.OUTPUT, "deliveries: 4 rows, every one in zone 9"),
    (Kind.MESSAGE, "Canada is zone 10 and no carrier prices it."),
)
"""What the mock does, in order and always the same.

A cycle rather than one repeated step, so a test can assert that each `Kind`
survives the trip to a subscriber — and so a page's trace shows more than one
glyph. `steps` longer than this repeats it; shorter truncates it."""


@dataclass(frozen=True)
class MockHarness:
    """A loop that does nothing, in the shape of one that does something."""

    name: str = "mock"
    steps: int = len(SCRIPT)
    delay_s: float = 0.0
    """Seconds between steps. **Zero by default: a unit test must not sleep.**
    Set it to watch a live stream arrive at a readable pace."""
    error: str | None = None
    """Set to exercise the failure path. The steps are still emitted — a loop
    that dies mid-way has already said what it was doing, and a record that
    forgot that is a record of nothing."""
    # Through a factory because a pydantic model is not hashable, which is how
    # `dataclass` decides a default is mutable enough to be shared by accident.
    answer: Answer = field(default_factory=lambda: ANSWER)
    usage: Usage = USAGE

    async def investigate(
        self,
        ticket: str,
        workdir: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> Outcome:
        emitted: list[Step] = []

        def happen(step: Step) -> None:
            """Reported as it happens, never replayed afterwards.

            A driver that collected its steps and handed them over at the end
            recorded a real investigation's twenty tool calls as none, and the
            judge graded a correct answer a lucky guess. A mock that replayed
            would let that defect back in without anyone seeing it, because the
            totals would still be right."""
            emitted.append(step)
            if on_step is not None:
                on_step(step)

        happen(Step(kind=Kind.STARTED, native="mock.started", text=ticket))
        for index in range(max(self.steps, 0)):
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            happen(_scripted(index))
        happen(Step(kind=Kind.FINISHED, native="mock.finished"))

        if self.error is not None:
            return Outcome(steps=emitted, usage=self.usage,
                           harness=self.name, error=self.error)
        return Outcome(answer=self.answer.model_dump(), steps=emitted,
                       usage=self.usage, harness=self.name)


def _scripted(index: int) -> Step:
    """One step of the cycle, with its index so two are never identical."""
    kind, text = SCRIPT[index % len(SCRIPT)]
    native = f"mock.{kind}"
    if kind is Kind.COMMAND:
        return Step(kind=kind, native=native, command=text)
    if kind is Kind.TOOL:
        return Step(kind=kind, native=native, tool=text,
                    args={"resource": "deliveries", "n": index})
    return Step(kind=kind, native=native, text=text, duration_ms=12 + index)


def build(
    steps: int = len(SCRIPT), delay_s: float = 0.0, error: str | None = None
) -> Callable[[Config], MockHarness]:
    """A factory shaped like the real drivers', for `Identity(name, build)`.

    Takes the settings a test employee has rather than reading them off a
    `Config`: a step count is nobody else's business, and putting it in the
    shared configuration object would make every real agent carry a field only
    this one reads. The harness is frozen and stateless, so one instance serves
    every ticket.
    """
    harness = MockHarness(steps=steps, delay_s=delay_s, error=error)
    return lambda _config: harness
