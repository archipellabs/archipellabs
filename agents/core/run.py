"""One investigation, from a ticket to an envelope — the only code path there is.

This module knows nothing about a bus. It builds the loop the identity names,
runs it, narrates what it does to whoever is listening, validates the verdict and
returns an envelope. `service` is what mounts it on the queue; a terminal, a test
or a campaign calls it directly and gets the same thing.

The split matters. Everything that made the four lineages diverge — who validates
the answer, which keys the envelope carries, when the record is written — lived
in each agent's own copy of a loop, so a fix in one was a fix in one. Here it is
written once and every employee inherits it.

**Events and the reply travel separately, and neither waits for the other.** The
caller does one `call` and waits for a value; a watcher subscribes and receives a
running commentary it never asked for. A step that reaches nobody is not an
error, and a watcher that has gone away must not be able to end an investigation.
"""

import asyncio
import contextlib
import logging
import time
from typing import Any, Protocol

from pydantic import ValidationError

from core import prices, record
from core.config import Config
from core.contract import Answer
from core.harness.base import Harness, Identity, Outcome, Step, Usage

log = logging.getLogger("core.run")

MAX_TEXT = 400
"""How much of a step's text goes on the bus.

Enough to see what is happening, not so much that a subscriber pays for the
investigation's whole output. The full step is in the run record; an event is a
window, not a copy."""

SKILL_PATH = ".agents/skills/"
"""Where a desk keeps its skills, so opening one can be recognised.

Inferred here rather than reported by a loop: codex has no such event, it runs a
command that happens to read a `SKILL.md`. The inference is about the desk, so it
belongs on this side of the translation."""


class Narrator(Protocol):
    """Where an investigation's events go.

    One method per topic rather than one method taking a topic name. A single
    `emit(topic, **fields)` would make every caller pass a string that only the
    implementation can check, and the compiler could not tell `analyst.stepp`
    from `analyst.step`.
    """

    async def started(self, **fields: Any) -> None: ...
    async def step(self, **fields: Any) -> None: ...
    async def finished(self, **fields: Any) -> None: ...


def as_event(step: Step) -> dict[str, Any]:
    """A step, translated for a subscriber.

    The second of two stages, and the split is the point. A driver turns its
    vendor's output into a `Step`, because it is the only thing that should know
    that vendor. This turns a `Step` into an event payload, because it is the
    only thing that should know what a subscriber reads. Neither knows the other.

    `step.native` is deliberately not published: an event carrying
    `item.completed` would let a subscriber branch on which loop ran, and the
    loop is what this lab keeps swapping.
    """
    return {
        "kind": str(step.kind),
        "tool": step.tool,
        "args": _arguments(step.args),
        "command": step.command[:MAX_TEXT],
        "text": step.text[:MAX_TEXT],
        "skill": _skill(step.command),
        "duration_ms": step.duration_ms,
    }


MAX_ARGS = 8
"""Arguments published per call. A named tool takes a handful; a loop that
grows one taking dozens should not be able to make an event larger than the
answer it is narrating."""


def _arguments(args: dict[str, Any]) -> dict[str, Any]:
    """A call's arguments, bounded for the wire.

    Published at all because a tool name alone says almost nothing: `shop_get`
    is every read this analyst ever makes, while `shop_get(resource=…)` is what
    it was actually looking for. They were dropped here while the record kept
    them, so a watcher saw the shape of an investigation and never its subject.

    Bounded because they are not all small. One loop's file-change arguments
    carry a whole patch, and an event is a window on a step rather than a copy
    of it — the full arguments are in the run record, which is what a grader
    reads.
    """
    kept: dict[str, Any] = {}
    for key, value in list(args.items())[:MAX_ARGS]:
        kept[key] = value[:MAX_TEXT] if isinstance(value, str) else value
    return kept


def _skill(command: str) -> str:
    """Which skill a command opened, if it opened one."""
    if SKILL_PATH not in command:
        return ""
    return command.split(SKILL_PATH, 1)[1].split("/", 1)[0]


async def investigate(
    identity: Identity,
    config: Config,
    ticket: str,
    *,
    reference: str | None = None,
    narrator: Narrator | None = None,
) -> dict[str, Any]:
    """Run one investigation and return the envelope describing it.

    **Returns, never raises.** The caller asked a question and deserves a value
    it can read; an exception would say the bus failed, which is a different
    fact and usually not the true one. A crash becomes `status="crashed"` with
    the transcript path still in hand.

    The loop is built per call rather than held on the service, so a change of
    model, depth or harness takes effect on the next ticket instead of the next
    restart.
    """
    run_id = record.new_id(identity.name)
    workspace = record.runs_dir() / run_id / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    steps: list[Step] = []
    published: list[asyncio.Task[None]] = []

    def collect(step: Step) -> None:
        """Called by the driver, from inside its own parsing. Never blocks it."""
        steps.append(step)
        if narrator is not None:
            published.append(
                asyncio.ensure_future(_publish(narrator, len(steps), step))
            )

    # **One exit, whatever went wrong.** A loop that cannot even be built used
    # to return here and then, having returned, skipped everything below: the
    # caller's `reference`, the `started` event, the `finished` event. A watcher
    # saw an investigation that never began and never ended, and the reply came
    # back unattributable. Every failure now walks the same path to the same
    # finalisation; only what it carries differs.
    harness: Harness | None = None
    outcome: Outcome | None = None
    crash: str | None = None

    try:
        harness = identity.build(config)
    except Exception as error:  # noqa: BLE001 — a loop that cannot be built is a result
        log.exception("%s could not build its loop", identity.name)
        crash = f"{type(error).__name__}: {error}"

    if narrator is not None:
        with contextlib.suppress(Exception):
            await narrator.started(
                run_id=run_id, agent=identity.name, ticket=ticket,
                model=config.model.name,
                harness=harness.name if harness is not None else "",
            )

    if harness is not None:
        try:
            outcome = await harness.investigate(ticket, workspace, collect)
        except Exception as error:  # noqa: BLE001 — the contract says drivers return
            log.exception("%s crashed outside its own error handling", harness.name)
            crash = f"{type(error).__name__}: {error}"

    # Every step published before the record is written, so a subscriber never
    # sees `finished` overtake the work it describes. Gathered rather than
    # awaited one by one: they were scheduled concurrently on purpose.
    if published:
        await asyncio.gather(*published, return_exceptions=True)

    if outcome is None:
        envelope = _envelope(
            identity, config, run_id, started, status="crashed", error=crash,
            calls=record.from_steps(steps),
        )
    else:
        envelope = _settle(identity, config, run_id, started, outcome, steps)

    envelope["reference"] = reference
    if narrator is not None:
        # Swallowed, like every other narration: the dependency runs the wrong
        # way if a broken watcher can lose an investigation that has finished.
        with contextlib.suppress(Exception):
            await narrator.finished(**envelope)
    return envelope


def _settle(
    identity: Identity,
    config: Config,
    run_id: str,
    started: float,
    outcome: Outcome,
    live: list[Step],
) -> dict[str, Any]:
    """One `Outcome`, checked against the contract and written down.

    The verdict is validated in exactly one place, for every loop. Three separate
    checks used to do this — a key-subset test, a required-fields test, and a
    type the model was held to — and only the third could say *why* an answer was
    unusable.
    """
    steps = outcome.steps or live
    answer: dict[str, Any] | None = None
    status = "failed"
    error: str | None = outcome.error

    if outcome.error:
        status = "crashed" if not outcome.answer else "failed"
    elif outcome.answer is None:
        error = "the loop finished without producing an answer"
    else:
        try:
            answer = Answer.model_validate(outcome.answer).model_dump()
            status = "completed"
        except ValidationError as invalid:
            # Named rather than swallowed: an answer nobody can read is a
            # different failure from an analyst that declined, and a run graded
            # zero deserves to say which it was.
            error = (
                "the answer did not match the contract: "
                f"{invalid.error_count()} problem(s)"
            )
            log.warning("%s returned an unusable answer: %s", identity.name, invalid)

    return _envelope(
        identity, config, run_id, started,
        status=status, answer=answer, error=error,
        harness=outcome.harness, usage=outcome.usage,
        calls=record.from_steps(steps),
    )


def _envelope(
    identity: Identity,
    config: Config,
    run_id: str,
    started: float,
    *,
    status: str,
    answer: dict[str, Any] | None = None,
    error: str | None = None,
    harness: str = "",
    usage: Usage | None = None,
    calls: list[record.ToolCall] | None = None,
) -> dict[str, Any]:
    """The one shape every employee returns, and the record beside it.

    Telemetry flat, verdict nested. Flat is what a campaign reads to build a cost
    table; nested is what a reader displays as the answer. Together in one
    dictionary they were the same thing, and a page rendering the verdict showed
    `cache_read_tokens` as a finding.
    """
    calls = calls or []
    spent = record.usage_fields(usage or Usage())
    duration_ms = int((time.monotonic() - started) * 1000)
    # **Priced at the final return, by the employee that knows what it ran.**
    # Only some loops are told what a turn was billed; that figure is
    # `cost`, a receipt, and it is never overwritten. This is the other
    # thing — tokens at a transcribed rate — computed here so a portal, a
    # report and a terminal are all handed the same number instead of each
    # keeping a table and drifting apart.
    if spent.get('cost') is None:
        spent['estimated_cost'] = prices.estimate(
            config.model.name,
            input_tokens=int(spent['input_tokens']),
            output_tokens=int(spent['output_tokens']),
            cache_read_tokens=int(spent['cache_read_tokens']),
        )

    written = record.Record(
        run_id=run_id,
        agent=identity.name,
        model=config.model.name,
        harness=harness or config.harness,
        status=status,
        calls=calls,
        output=answer,
        error=error,
        duration_ms=duration_ms,
        effort=config.model.reasoning,
        **{k: v for k, v in spent.items() if k != "model_requests"},
        model_requests=spent["model_requests"],
    )
    transcript = written.write(record.runs_dir())

    return {
        "run_id": run_id,
        "agent": identity.name,
        "status": status,
        "harness": harness or config.harness,
        "model": config.model.name,
        "effort": config.model.reasoning,
        "duration_ms": duration_ms,
        "tool_calls": len(calls),
        **spent,
        # The neutral record, for every employee. A lineage that also keeps a
        # verbatim artifact of its own still writes it — it is simply not the
        # one a grader reads, because two readers report figures that depend
        # on which lineage a row came from.
        "transcript": str(transcript),
        "answer": answer,
        "error": error,
    }


async def _publish(narrator: Narrator, n: int, step: Step) -> None:
    """One step, fired and forgotten."""
    with contextlib.suppress(Exception):
        await narrator.step(n=n, **as_event(step))
