"""Driving `opencode serve`, in the part that does not depend on the employee.

Two employees run on opencode and they are equipped very differently. One is
handed a **desk** — an `AGENTS.md`, a directory of skills, a shell — and finds
the company by running commands. The other is handed an **MCP server** and no
shell at all, and finds the company by calling typed tools. That difference is
the experiment, and it is the whole of what `opencode_cli` and `opencode_mcp`
still hold separately.

Everything between those two ends was the same code twice: start a server on a
free port with its configuration injected through the environment, open a
session, post the ticket, read the conversation back, translate it into `Step`s,
sum what the turn spent, and dig the verdict out of the prose. Written twice it
drifted, which is not a hypothetical: one copy learned that a refused tool call
carries `error` and no `output` at all, and the other did not — so on that side
six blocked commands were recorded as six empty successes, and an answer built on
evidence the loop had never been allowed to gather read exactly like a clean run.

The module is named for the API rather than for the tool, like its two callers:
importing any of them must never be able to shadow the binary they drive.
"""

import asyncio
import contextlib
import json
import pathlib
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from core.contract import Answer
from core.harness.base import Kind, Outcome, Step, Usage

HARNESS = "opencode"
"""What a record calls this loop, whichever way the employee is equipped.

One name for both drivers, deliberately. A record already says *who* ran — and
`charlie` and `philip` are the two ways opencode is used here — so a second name
would split one loop into two in every table that groups by harness."""

SCHEMA = "https://opencode.ai/config.json"
"""The `$schema` opencode's own configuration declares."""

START_TIMEOUT = 30.0
"""How long to wait for `opencode serve` to accept a connection."""

REPLY_CHARS = 2000
"""How much of the turn's own HTTP reply is kept for an error message.

opencode answers 2xx for a turn that never ran and puts the reason in that body,
so throwing it away left a driver blaming the model's output formatting for a
provider rejection — and a reader debugging the wrong thing entirely."""


# ── the conversation, as standard steps ──────────────────────────────────────


OPENCODE_PARTS: dict[str, Kind] = {
    "reasoning": Kind.THINKING,
    "text": Kind.MESSAGE,
    "step-start": Kind.STARTED,
    "step-finish": Kind.FINISHED,
}
"""opencode's *part* vocabulary, mapped into the standard one.

**Parts, not events.** opencode's live SSE stream names the same beats
differently, and a second table for those once existed beside this one. If
streaming is ever built, write it again rather than reaching for this: a
conversation read back afterwards and a live stream are two vocabularies for one
run, and collapsing them into one table silently mistranslates whichever lost.

`tool` is absent on purpose: one tool part carries both the call and its result,
so it becomes two steps rather than one. Everything unlisted arrives as `OTHER`
with its native name attached, so a release that grows a part type shows up in
the stream instead of vanishing here.
"""


def steps(messages: Any) -> list[Step]:
    """An opencode conversation as standard steps.

    Written from a persisted run rather than from the API docs. The shape is
    `[{info: {role, tokens}, parts: [{type, tool, state: {input, output}}]}]`,
    and guessing it is how the codex mapper was wrong for a whole campaign while
    its unit test agreed with it.

    A call and its result become **two** steps, which is what `record.from_steps`
    walks to pair them back up: one pairing, in one place, rather than the three
    reconstructions this repository has written.
    """
    found: list[Step] = []
    for message in messages if isinstance(messages, list) else []:
        for part in message.get("parts") or []:
            native = str(part.get("type") or "")
            if native == "tool":
                found.extend(_tool_steps(part, native))
                continue
            found.append(
                Step(
                    kind=OPENCODE_PARTS.get(native, Kind.OTHER),
                    native=native,
                    text=str(part.get("text") or ""),
                    command="",
                )
            )
    return found


def _tool_steps(part: dict[str, Any], native: str) -> list[Step]:
    """One tool part as the call it made and the result it got."""
    state = part.get("state") or {}
    given = state.get("input")
    arguments = dict(given) if isinstance(given, dict) else {}
    # `bash` is the shell, and a shell command belongs in `command` where the
    # rest of this package looks for one — which skill a run opened is inferred
    # from it. The named tools carry structured arguments instead of a command
    # line, and this used to flatten both into `f"{name} {json}"` for the layer
    # above to split apart on the first space: `read`, `grep` and `apply_patch`
    # all reached the record as a `command`, which is the one thing they never
    # had. Every tool the MCP driver offers is of that second sort.
    command = str(arguments.get("command") or "")
    # A refused call has no `output` key AT ALL — it carries `error` and
    # `status: "error"`. Reading only `output` turned six blocked commands into
    # six empty successes in one real run: the judge saw `{"status": "ok",
    # "output": ""}` and read them as commands that simply returned nothing,
    # while the answer was built on evidence the loop had never been allowed to
    # gather. A refusal must look like a refusal.
    status = str(state.get("status") or "")
    called = Step(
        kind=Kind.COMMAND if command else Kind.TOOL,
        native=native,
        tool=str(part.get("tool") or ""),
        args=arguments,
        command=command,
        duration_ms=_elapsed(state.get("time")),
    )
    # **A call that has not finished gets no result step.** A conversation read
    # back while the turn is still in flight carries parts marked `running`, and
    # anything-that-is-not-`error` used to become a plain `OUTPUT` — so a call
    # still executing was recorded as one that had returned, with empty output
    # and a clean status. The record then said the loop had read something it
    # was in fact still waiting for. Left open, it is recorded `pending`, which
    # is what it is.
    if status not in ("completed", "error"):
        return [called]
    return [
        called,
        Step(
            kind=Kind.ERROR if status == "error" else Kind.OUTPUT,
            native=native,
            text=str(state.get("error") or state.get("output") or ""),
            command="",
        ),
    ]


def _elapsed(span: Any) -> int | None:
    """How long one tool call took, from the epoch milliseconds opencode stamps.

    `{"start": ..., "end": ...}`, present on all 1103 tool parts of the persisted
    corpus — which is where the shape came from rather than the docs. `None`
    while a call is still open, because "not finished" and "took no time" are
    different facts and a record that cannot tell them apart is the reason
    per-call latency had to be reconstructed once already.
    """
    if not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    if not isinstance(start, int | float) or not isinstance(end, int | float):
        return None
    return int(end - start)


# ── what the turn spent, and what it concluded ───────────────────────────────


def usage(messages: Any) -> Usage:
    """What the turn spent, summed from the messages that spent it.

    opencode reports per message, under `info.tokens`, and a turn is many
    messages — so these are summed rather than taken from the last one. Reading
    only codex's shape left every opencode cost cell empty, which the report
    rendered as a dash and a reader could easily have taken for a cheap run
    rather than an unmeasured one.

    **`input` here EXCLUDES cached tokens** — opencode reports `total = input +
    output + cache.read`, verified exactly on every persisted message. codex's
    `input_tokens` INCLUDES its cached subset. Left unreconciled, one column held
    two different quantities and a campaign compared a cache-inclusive figure
    against a cache-exclusive one, a ~7x difference on a real record. Both
    drivers normalise to "everything sent", with the cached part reported
    separately.

    One assistant message is one model request, so counting the messages that
    carry tokens is a measurement rather than an estimate — the count codex
    cannot give. `cost` is opencode's own figure per message, summed the same way
    and never derived from a price table here; zero becomes `None`, because a run
    whose provider had no price is unmeasured rather than free.
    """
    requests = 0
    sent = received = reasoning = cached = 0
    cost = 0.0
    for message in messages if isinstance(messages, list) else []:
        info = message.get("info") or {}
        tokens = info.get("tokens") or {}
        if not tokens:
            continue
        read = int((tokens.get("cache") or {}).get("read") or 0)
        requests += 1
        sent += int(tokens.get("input") or 0) + read
        received += int(tokens.get("output") or 0)
        reasoning += int(tokens.get("reasoning") or 0)
        cached += read
        cost += float(info.get("cost") or 0.0)
    return Usage(
        model_requests=requests,
        input_tokens=sent,
        output_tokens=received,
        reasoning_tokens=reasoning,
        cache_read_tokens=cached,
        cost=cost or None,
    )


def turn_error(messages: Any) -> str:
    """The turn's own failure, if it reported one.

    `{"info": {"error": {"name": ..., "data": {"message": ...}}}}`. Read from a
    real failing turn, not from the docs: the shape that surfaced here was
    `ProviderAuthError` with *"OpenAI API key is missing"*, which the driver had
    been reporting as a malformed answer.
    """
    for message in messages if isinstance(messages, list) else []:
        error = (message.get("info") or {}).get("error") or {}
        if error:
            name = str(error.get("name") or "error")
            detail = str((error.get("data") or {}).get("message") or "")
            return f"opencode turn failed: {name}: {detail}".strip()
    return ""


def assistant_text(messages: Any) -> str:
    """Every assistant text part, concatenated."""
    if not isinstance(messages, list):
        return ""
    chunks: list[str] = []
    for message in messages:
        info = message.get("info", message) if isinstance(message, dict) else {}
        if info.get("role") != "assistant":
            continue
        for part in message.get("parts", []) if isinstance(message, dict) else []:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(str(part.get("text", "")))
    return "\n".join(chunks)


def verdict(text: str) -> dict[str, Any] | None:
    """The last JSON object in the prose that carries the answer's shape.

    Last rather than first: a model that reasons before answering often prints a
    draft on the way.

    Recognised by `Answer` rather than by a key-subset test against the schema,
    so "matches the answer shape" means one thing in this repository. Returned as
    the model wrote it, not as the validated model dumps: `run.investigate`
    validates every loop's verdict in one place, and a driver that quietly
    normalised its own would be the one loop held to a different contract.
    """
    found: dict[str, Any] | None = None
    for start in range(len(text)):
        if text[start] != "{":
            continue
        for end in range(len(text), start, -1):
            if text[end - 1] != "}":
                continue
            try:
                candidate = json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and _is_answer(candidate):
                found = candidate
            break
    return found


def _is_answer(candidate: dict[str, Any]) -> bool:
    """Whether one JSON object is a verdict rather than something else."""
    try:
        Answer.model_validate(candidate)
    except ValidationError:
        return False
    return True


# ── one investigation ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Turn:
    """One posted ticket and everything the server said about it."""

    messages: Any
    """The conversation as opencode returns it: a list of
    `{info: {role, tokens, error}, parts: [...]}`."""
    reply: str
    """The body of the POST that started the turn, clipped. Kept because a turn
    that never ran still answers 2xx, and this is where it says why."""


@dataclass(frozen=True)
class Session:
    """What one investigation needs from the server, whatever equips it.

    The two drivers differ in exactly four of these — the directory the server
    runs in, the environment it is given, the configuration it is started with,
    and the brief — and agree on everything else. Naming them as fields is what
    makes that sentence checkable rather than a claim about two files.
    """

    cwd: pathlib.Path
    """Where `opencode serve` runs. A scratch workspace for the desk driver,
    whose skills were copied into it; the employee's own project for the MCP
    driver, whose tool server is launched from there."""
    env: dict[str, str]
    """The complete environment the server process is given. Built by the caller,
    because what a loop can reach is the boundary this lab varies."""
    config: dict[str, Any]
    """opencode's own configuration, injected through `OPENCODE_CONFIG_CONTENT`
    rather than written to a file, so nothing about the role — or a provider key
    — lands on disk beside the code."""
    provider: str
    model: str
    system: str
    """The brief, passed explicitly rather than discovered. Two harnesses reading
    different briefs would make every comparison between them a comparison of
    briefs."""
    timeout_s: float = 900.0
    read_steps: Callable[[Any], list[Step]] = steps
    """How this employee's conversation becomes steps.

    A seam, because one driver knows something the other cannot: the MCP tools
    never raise, they answer `{"error": ...}`, so a call opencode reports
    `completed` may still be a refusal. That is a fact about those tools rather
    than about opencode, and teaching it to `steps` would make every shell
    command whose output happens to be JSON carrying an `error` field a failed
    call on the desk side too.
    """


async def converse(http: httpx.AsyncClient, session: Session, ticket: str) -> Turn:
    """Open a session, put the ticket in, read everything back.

    Separated from the server lifecycle so it can be checked against a fake
    opencode without launching one. That matters more than it sounds: the two
    worst bugs on this path were in this request's shape, and both were found by
    running a three-minute campaign and reading a record afterwards.

    **The turn is replayed, not streamed, and that is a choice rather than a
    limit.** opencode does stream: the server publishes 45 event types over
    server-sent events and documents them at `/doc`. An earlier driver claimed
    it could not and explained the supposed limitation at length; the limitation
    was the driver's. A live subscriber was then written, and never wired in —
    it sat unreferenced until it was deleted, so this replay has always been the
    real path. Reading the conversation back afterwards cannot perturb the run
    and gives the same steps.

    If it is ever streamed, the trap is recorded here so it need not be
    rediscovered: **subscribe before posting the message.** Opening the stream
    afterwards races the first events and loses them, which looks exactly like a
    model that thought for a while before starting.
    """
    created = await http.post("/session", json={})
    created.raise_for_status()
    session_id = created.json()["id"]

    answered = await http.post(
        f"/session/{session_id}/message",
        json={
            # NESTED under `model`. Sent flat as `providerID` and `modelID`,
            # opencode accepts them, ignores them without complaint and runs its
            # own default. The run then reports one model request, no tokens and
            # no tool calls, and reads exactly like a model that refused to work.
            "model": {"providerID": session.provider, "modelID": session.model},
            "system": session.system,
            "parts": [{"type": "text", "text": ticket}],
        },
    )
    answered.raise_for_status()

    listed = await http.get(f"/session/{session_id}/message")
    listed.raise_for_status()
    return Turn(messages=listed.json(), reply=answered.text[:REPLY_CHARS])


async def run(
    session: Session,
    ticket: str,
    on_step: Callable[[Step], None] | None = None,
) -> Outcome:
    """One investigation on a server of its own, from ticket to verdict.

    **Returns, never raises**, for anything the loop itself can go wrong at: the
    bus already reports its own failures, and conflating the two makes a broken
    model look like a broken broker.

    The server is started **per investigation** rather than shared. A session
    inherits the server's project directory and configuration, so a long-lived
    server would mean every later run silently reusing whichever directory and
    credentials the first one happened to start with.
    """
    try:
        async with serving(session.cwd, session.env, session.config) as base_url:
            async with httpx.AsyncClient(
                base_url=base_url, timeout=session.timeout_s
            ) as http:
                turn = await converse(http, session, ticket)
    except (OSError, httpx.HTTPError, RuntimeError, TimeoutError) as error:
        return Outcome(harness=HARNESS, error=f"{type(error).__name__}: {error}")

    taken = session.read_steps(turn.messages)
    spent = usage(turn.messages)

    # Replay the turn as standard steps. Not live — the whole conversation is
    # read back once it is over — but a subscriber that never hears what a run
    # did is worse than one that hears it late. This was missing once and cost a
    # grade: a campaign recorded an investigation of twenty tool calls as having
    # made none, and the judge graded a correct answer `lucky guess`.
    if on_step is not None:
        for step in taken:
            on_step(step)

    # opencode reports a turn's own failure inside the message rather than in the
    # HTTP status, so a provider rejection arrives as a 2xx with no assistant
    # text. Reported before the shape check, or an auth error is announced as bad
    # output formatting — which is what sent a full day of opencode functional
    # failures to the wrong suspect.
    refused = turn_error(turn.messages)
    if refused:
        return Outcome(steps=taken, usage=spent, harness=HARNESS, error=refused)

    answer = verdict(assistant_text(turn.messages))
    if answer is None:
        return Outcome(
            steps=taken,
            usage=spent,
            harness=HARNESS,
            error=(
                "opencode returned no JSON object matching the answer shape; "
                f"the turn's own reply was: {turn.reply}"
            ),
        )
    return Outcome(answer=answer, steps=taken, usage=spent, harness=HARNESS)


# ── the server process ───────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def serving(
    cwd: pathlib.Path, env: dict[str, str], config: dict[str, Any]
) -> AsyncIterator[str]:
    """A headless opencode, alive only for this investigation.

    The environment is taken whole rather than merged with this process's own.
    What a loop can reach is a decision each driver makes and states, and a
    default here would quietly overrule it.
    """
    port = free_port()
    process = subprocess.Popen(
        ["opencode", "serve", "--port", str(port)],
        cwd=cwd,
        env={**env, "OPENCODE_CONFIG_CONTENT": json.dumps(config)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + START_TIMEOUT
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"opencode serve exited with {process.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"opencode serve did not listen within {START_TIMEOUT}s"
                    ) from None
                await asyncio.sleep(0.25)
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
