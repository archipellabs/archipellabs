"""What a run leaves behind, in the shape a grader should have to read.

Three loops produce investigations and they record them very differently. This is
the neutral form all of them write, chosen by comparing them rather than by
defaulting to whichever came first.

**One record per tool call, holding its own result.** pydantic-ai splits a call
and its return across two messages, paired by `tool_call_id`; every consumer then
rebuilds the pairing, and this repository has written that reconstruction three
times. opencode keeps them together, and that is plainly better: the pairing
cannot be got wrong if it is never taken apart.

**Status is declared, not inferred.** A grader that decides a call failed by
matching `"error":` against its serialized output will lie the first time a tool
legitimately returns a field called `error`. The loops state `completed` or
`error`; so does this.

**Timing is part of the record.** Per-call latency had to be added to one lineage
by instrumenting its event stream. It is the difference between "the run took ten
minutes" and "the log store took nine of them", and a format that cannot carry it
forces that question to be unanswerable after the fact.

**Keep unconditionally.** Drivers used to work in a temporary directory and
delete it on the way out: the answer survived, everything that produced it did
not. The first repair kept a transcript only when the answer came back empty, on
the theory that an empty answer is the interesting failure. The very next run
answered confidently and was wrong about every figure. A wrong answer is a more
interesting failure than no answer, and neither is knowable before the run ends.

The verdict and the usage totals ride along, so one file answers what was done,
what it cost, and what was concluded.
"""

import json
import os
import pathlib
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from core.harness.base import Kind, Step, Usage

VERSION = 1
"""Bumped when a field changes meaning. A grader reading a record it does not
recognise should say so rather than score it."""

MAX_OUTPUT_CHARS = 4000
"""How much of a tool's return is stored per call.

Generous — this is the evidence, not a log line — but bounded, because one loop
returned a 115 KB payload from a single call and a record holding a hundred of
those stops being something a grader can open."""


@dataclass
class ToolCall:
    """One tool call and everything that happened to it."""

    tool: str
    input: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    status: str = "pending"
    """`pending`, `completed` or `error`, from the loop — never guessed from
    the text.

    **`pending` is the default, and that is the correction.** It used to be
    `completed`, so a call nothing ever closed — a run killed mid-command, a
    turn read back while still running — was recorded as a command that
    succeeded. Silently, and in the direction that flatters: a grader counting
    what an investigation managed to read counted work that never returned. A
    call is finished when something says it is."""
    duration_ms: int | None = None
    output_chars: int = 0
    """The size handed back to the model, which is resent on every later turn.
    Not the size of `output` here, which may have been clipped for storage."""


@dataclass
class Record:
    """One investigation, whoever ran it."""

    run_id: str
    agent: str
    model: str
    harness: str
    """Which loop drove it. The variable under test, so it is recorded."""
    status: str
    calls: list[ToolCall] = field(default_factory=list)
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    """Billed, and invisible inside `output_tokens`. Recorded separately because
    depth is now a per-ticket choice: two runs differing only by the one lever
    measured to move wall clock would otherwise be indistinguishable afterwards."""
    cache_read_tokens: int = 0
    model_requests: int = 0
    effort: str = ""
    cost: float | None = None
    """What the loop was billed, when the loop is told. A receipt, not a
    reckoning — only some providers report one."""
    estimated_cost: float | None = None
    """The same run priced from `prices.RATES`: tokens at a transcribed rate.

    A separate field from `cost` because it is a separate claim, and a report
    that added them or preferred one silently would be publishing arithmetic as
    a charge. `None` when the model is unpriced, which is not the same as free."""
    version: int = VERSION

    def write(self, directory: pathlib.Path) -> pathlib.Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.record.json"
        path.write_text(json.dumps(asdict(self), indent=2, default=str))
        return path


def read(path: pathlib.Path) -> Record:
    """Load a record, refusing a version this code does not understand.

    Silently scoring an unrecognised shape is how a grader reports a confident
    zero about a run it could not read — which has happened here twice.
    """
    raw = json.loads(path.read_text())
    if raw.get("version") != VERSION:
        raise ValueError(
            f"{path.name} is record version {raw.get('version')}, this reads {VERSION}"
        )
    calls = [ToolCall(**call) for call in raw.pop("calls", [])]
    return Record(**{**raw, "calls": calls})


def new_id(agent: str) -> str:
    """A run id nobody else will mint.

    Prefixed with the employee's name rather than a lineage letter. Two agents
    once both minted `i_…` into the same transcript directory, so whose evidence
    a file held was decided by luck.
    """
    return f"{agent}_{uuid.uuid4().hex[:12]}"


def runs_dir() -> pathlib.Path:
    """Where this employee's runs land.

    Resolved per call, never bound at import. `AGENT_TRANSCRIPT_DIR` is set by a
    caller that imports this module first — the research runner sets it inside a
    function so a campaign's transcripts land beside the report citing them. Read
    at import, the variable was read before that assignment and every campaign
    silently wrote somewhere else.
    """
    given = os.environ.get("AGENT_TRANSCRIPT_DIR")
    return pathlib.Path(given) if given else pathlib.Path.cwd() / "runs"


_OPENS = (Kind.COMMAND, Kind.TOOL)
"""The two kinds that open a call. Everything else closes one or is prose."""


def from_steps(steps: list[Step]) -> list[ToolCall]:
    """The call-and-result pairing, rebuilt once here instead of everywhere.

    A loop reports a call and then, separately, what it returned. This walks the
    stream and closes each open call with the `OUTPUT` or `ERROR` that follows
    it — one place the pairing can be got wrong rather than the three it used to
    be.

    **An `ERROR` closes a call as failed.** A command that exited non-zero is a
    refusal, a 401, a missing binary — not a result. Recorded as a plain output,
    a `curl` that 401'd and a `curl` that returned the orders are the same event
    to everything downstream, the judge included.

    An `ERROR` with nothing open is the loop's own failure and gets a call of its
    own, so a run that died before doing anything is not an empty list
    indistinguishable from a run that simply did nothing.

    **A result closes the call it names, not the one before it.** When a loop
    reports a `call_id`, that is what joins the two. Position alone is wrong for
    any loop that runs a turn's calls concurrently — and one of the three does:
    two reads in flight together return in whichever order they finish, so the
    slower one is recorded with no output and the faster result is attributed to
    a call nobody made. Loops that report no id are strictly sequential, so they
    fall back to position and lose nothing.
    """
    calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    pending: ToolCall | None = None

    for step in steps:
        if step.kind in _OPENS:
            pending = ToolCall(
                tool=step.tool or step.command or str(step.kind),
                input=_input_of(step),
                duration_ms=step.duration_ms,
            )
            calls.append(pending)
            if step.call_id:
                by_id[step.call_id] = pending
        elif step.kind in (Kind.OUTPUT, Kind.ERROR):
            answered = by_id.pop(step.call_id, None) if step.call_id else pending
            if answered is None:
                answered = ToolCall(tool=step.tool or step.native or str(step.kind))
                calls.append(answered)
            answered.output = step.text[:MAX_OUTPUT_CHARS]
            answered.output_chars = len(step.text)
            answered.status = "error" if step.kind is Kind.ERROR else "completed"
            if step.duration_ms is not None:
                answered.duration_ms = step.duration_ms
            if answered is pending:
                pending = None

    return calls


def _input_of(step: Step) -> dict[str, Any]:
    """A call's arguments, however the loop expressed them."""
    if step.args:
        return dict(step.args)
    return {"command": step.command} if step.command else {}


def usage_fields(usage: Usage) -> dict[str, Any]:
    """A `Usage` as the flat keys a record and an envelope both carry."""
    return {
        "model_requests": usage.model_requests,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cost": usage.cost,
    }
