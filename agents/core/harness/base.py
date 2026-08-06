"""What a harness is, and what it must return.

A harness is the loop: it takes a ticket, drives a model until it stops, and
hands back an answer plus a record of what happened. Everything above this line
is the employee's job; everything below it belongs to whichever loop is doing the
driving — pydantic-ai in this process, codex or opencode in a subprocess.

The interface exists because the loop is **a variable under test**. Two campaigns
in one week were decided by different things, and on one of them the harness
explained the entire gap while the model explained none of it. A design that
hard-codes one loop cannot notice that.

`Outcome` carries the steps as well as the answer. An answer alone cannot be
audited: a correct verdict over an investigation that never happened reads
exactly like a success, and the record is the only thing that tells them apart.
"""

import pathlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from core.config import Config


class Kind(StrEnum):
    """What a step is, in words no loop invented.

    A closed vocabulary, and that is the whole point of it. The drivers speak
    `item.completed`, `message.part.updated` and `FunctionToolCallEvent`;
    anything above them that branched on those would be coupled to a vendor's
    release notes. So each driver maps into this, and everything downstream
    consumes only this.

    `OTHER` is deliberate. A loop that grows a step type should arrive in the
    stream as something rather than be dropped by a translator that has not been
    taught about it yet; `native` says what it was.
    """

    STARTED = "started"
    """The loop began work."""
    THINKING = "thinking"
    """A model turn: the agent is deciding, not doing."""
    COMMAND = "command"
    """A shell command was run. `command` carries it."""
    OUTPUT = "output"
    """What a command or tool returned."""
    MESSAGE = "message"
    """The agent said something in prose."""
    TOOL = "tool"
    """A tool call that is not a shell command. `tool` and `args` carry it."""
    FINISHED = "finished"
    """The loop stopped of its own accord."""
    ERROR = "error"
    """The loop reported a failure, which is not the same as the run failing."""
    OTHER = "other"


@dataclass(frozen=True)
class Step:
    """One thing a loop did, in a shape no loop invented.

    The three loops report in their own vocabularies: codex streams JSONL items,
    opencode returns a conversation, pydantic-ai raises typed events.
    Translating that in the driver that already has to know the vendor is what
    keeps everything above from knowing it too. An app reaching into
    `step["item"]["aggregated_output"]` would be an app coupled to codex.

    There was a `raw` field holding the vendor's whole payload, justified by
    "the record should hold what actually happened, not only what this shape has
    room for". The record has no room for it and never did: `ToolCall` has no
    such field and `Record` does not carry steps at all. So it was written by
    every driver, read by nobody, and retained in memory for every step of every
    run — a promise the format could not keep. If a payload is worth keeping,
    the honest fix is a field on the record, not a field on the way to it.
    """

    kind: Kind
    """The standard word. Never the vendor's."""
    native: str = ""
    """The vendor's word, kept for a human reading a record.

    **Nothing branches on it, and nothing should** — the moment something does,
    the app knows which loop it is talking to. The one consumer is
    `record.from_steps`, which uses it as a last-resort *name* for a call the
    loop failed before naming: a label, not a decision."""
    text: str = ""
    tool: str = ""
    """The name of a tool that is not a shell command.

    Separate from `command` rather than folded into it. One driver used to encode
    a named call as `f"{tool} {json.dumps(args)}"` and the layer above split it
    back apart on the first space, which is why its records hold
    `input={"command": "..."}` instead of the arguments the model actually
    passed. A structured call deserves structured fields."""
    args: dict[str, Any] = field(default_factory=dict)
    """That tool's arguments, as the loop reported them."""
    call_id: str = ""
    """Which call this step belongs to, when the loop says.

    A result is a separate step from the call it answers, and something has to
    join them back up. Position alone does not: pydantic-ai runs a turn's calls
    **concurrently** and emits each result as it completes, so two reads in
    flight together come back in whichever order they finish. Paired by
    position, the slower call is recorded with no output at all and the faster
    result is attributed to a call nobody made.

    Empty when a loop reports no id — codex and opencode are strictly
    sequential, so position is sound there and the fallback is correct rather
    than merely tolerated."""
    command: str = ""
    duration_ms: int | None = None
    """How long the call took, when the loop can say.

    The difference between "the run took ten minutes" and "the log store took
    nine of them". A shape that cannot carry it forces that question to be
    unanswerable after the fact."""


@dataclass(frozen=True)
class Usage:
    """What one investigation spent, counted by the loop that spent it.

    Reported by the driver rather than reconstructed above it. The alternative
    was tried: a shared layer that read codex's `turn.completed.usage` *and*
    opencode's `info.tokens.cache.read` needed forty lines of comment to
    reconcile a cache-inclusive count against a cache-exclusive one, in a module
    whose entire purpose was not to know which loop it held. The driver already
    knows its vendor. Let it do the arithmetic once.
    """

    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    """Billed and invisible in `output_tokens`. Counted on one side only, "both
    loops think at the same depth" becomes a setting rather than a measurement."""
    cache_read_tokens: int = 0
    cost: float | None = None
    """Only when the loop reports one. Never derived from a price table here: a
    figure this repository computed would be a figure it could publish wrong."""


@dataclass(frozen=True)
class Outcome:
    """One investigation, as it will be recorded."""

    answer: dict[str, Any] | None = None
    """The verdict, unvalidated. `run.investigate` is what checks its shape, so
    every loop is held to one contract in one place."""
    steps: list[Step] = field(default_factory=list)
    """Normalised, unlike the vendor-native list this replaced. That list forced
    every consumer to learn each driver's internals to count a tool call, which
    is the coupling this interface exists to avoid."""
    usage: Usage = field(default_factory=Usage)
    harness: str = ""
    error: str | None = None
    """Set when the loop failed to produce an answer. A failure is a value here,
    not an exception: the caller asked a question and can read this."""

    # There was a `kept` field here, letting a driver point the envelope's
    # `transcript` at a richer artifact of its own. Exactly one driver had one —
    # pydantic-ai's verbatim message history — and it stopped pointing at it the
    # day every employee began writing the neutral record, because a grader with
    # two readers reports figures that depend on which lineage a row came from.
    # The field then had no producer at all. It still writes that file; see
    # `pydantic_ai.keep`, which records why it is written and not named.


class Harness(Protocol):
    """A loop that can be handed a ticket."""

    @property
    def name(self) -> str:
        """Which loop this is, for the record that has to say.

        A read-only property rather than a plain attribute, so a driver may be a
        frozen dataclass. Declared mutable, the protocol demands a settable
        attribute and quietly excludes every immutable implementation — which is
        the shape a stateless driver should have."""
        ...

    async def investigate(
        self,
        ticket: str,
        workdir: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> Outcome:
        """Run once in `workdir`, which is already laid out as a desk.

        `on_step` is called as each step happens, if the loop can report them
        live. A callback and not a runtime context: a driver that imported the
        bus to publish would be a driver that cannot run without one, and these
        are meant to be swappable. Whoever wants the steps on a bus wraps them.

        Synchronous, because the drivers call it from the middle of parsing a
        vendor's stream. Making it awaitable would push an event loop into code
        whose only job is translation.

        The directory is given rather than made. A driver that created its own
        temporary directory also destroyed it, and with it every trace of how the
        answer was reached; ownership belongs to whoever wants to keep it.

        Must return, never raise, for anything the loop itself can go wrong at:
        the bus already reports its own failures, and conflating the two makes a
        broken model look like a broken broker.
        """
        ...


@dataclass(frozen=True)
class Identity:
    """Who an employee is, in the two things that cannot be shared.

    Everything else in this package is machinery. This is the seam: a name, and
    how to build the loop that name runs on. An agent's own package holds its
    tools or its desk and one file that says how to assemble them.

    A name rather than a bare callable, because the name is not decoration — it
    is the service, the action the bus routes on (`angel.investigate`), the
    `agent` field on every event, and the prefix of every run id. Passing the
    factory alone would mean re-deriving all four from somewhere else.
    """

    name: str
    build: Callable[[Config], Harness]

    def __post_init__(self) -> None:
        # A name reaching the queue as `angel.investigate` must not be able to
        # carry a dot of its own, or one employee could claim another's action by
        # being called "angel.investigate" itself.
        if not self.name or not self.name.isidentifier():
            raise ValueError(
                f"agent name must be a plain identifier, got {self.name!r}"
            )

    @property
    def investigate(self) -> str:
        """The action this employee answers to.

        Derived here rather than by a second object holding a copy of the name.
        There was one, and it re-validated the identifier to protect the same
        invariant — an invariant written twice is an invariant that has to stay
        right twice.

        The **events** are deliberately not properties of this class: they are
        shared across the staff, and hanging them off a per-employee object
        would say the opposite. They are module constants in `topics`.
        """
        return f"{self.name}.investigate"
