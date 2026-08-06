"""The codex loop, driven as a subprocess.

`codex exec` is unusually well suited to being driven: `--json` streams the
turn as JSONL, `--output-schema` makes the final message conform to a shape, and
`-o` writes that message to a file instead of leaving it to be scraped out of
prose. So this driver parses a contract rather than reverse-engineering output.

Three flags are not optional, and each cost a debugging round to find:

`stdin` must be closed. Off a terminal, `codex exec` announces *reading
additional input from stdin* and waits for an EOF that never arrives. It hangs
forever with no output at all, which reads exactly like a model thinking.

`--skip-git-repo-check`, because the working directory is a scratch directory
rather than a repository, and codex refuses to run untrusted directories.

What it is allowed to do lives in `policy`, not here: both harnesses answer to
one statement of the role, so a campaign comparing them is comparing loops
rather than two sets of permissions.
"""

import asyncio
import contextlib
import json
import os
import pathlib
import signal
from collections.abc import Callable
from typing import Any

from core.config import Config
from core.contract import ANSWER_SCHEMA
from core.harness.base import Harness, Kind, Outcome, Step, Usage
from core.harness.desk import Desk, child_env, prepare
from core.harness.policy import CODEX_CONFIG, CODEX_SANDBOX

BINARY = "codex"


def build(config: Config, desk: Desk) -> Harness:
    """The codex loop, as one employee's configuration describes it.

    The desk is passed rather than found. Which brief and which credentials a
    loop runs with is the employee's, and this driver is shared by all of them.
    """
    return CodexHarness(
        desk=desk,
        # Computed once, here, because this is the only place holding both the
        # desk (which names what the role may reach) and the configuration
        # (which holds the values). The harness carries the result, not the
        # configuration: one dict of strings to hand a subprocess.
        env=child_env(desk, config),
        model=config.model.name,
        effort=config.model.reasoning,
        timeout_s=config.timeout_s,
    )


def build_argv(
    desk: Desk,
    schema: pathlib.Path,
    answer: pathlib.Path,
    model: str,
    ticket: str,
    effort: str = "",
) -> list[str]:
    """The full command, assembled where it can be read and tested.

    Every element earns its place: `--json` for the record, `--output-schema`
    and `-o` for an answer that is parsed rather than scraped,
    `--skip-git-repo-check` because the working directory is scratch, and
    `--strict-config` so a policy key codex no longer knows stops the run
    instead of being dropped in silence.
    """
    argv = [
        BINARY, "exec",
        "--json",
        "--skip-git-repo-check",
        "--strict-config",
        "--sandbox", CODEX_SANDBOX,
        "--output-schema", str(schema),
        "-o", str(answer),
    ]
    for key, value in CODEX_CONFIG.items():
        # The only templated setting: the environment allow-list is the desk's,
        # so a variable added there reaches the shell without a second edit.
        if "{names}" in value:
            allowed = (*desk.company_env, "PYTHON", "COMPANY_CA", "PATH")
            value = value.format(names=",".join(f'"{name}"' for name in allowed))
        argv += ["-c", f"{key}={value}"]
    if model:
        argv += ["--model", model]
    if effort:
        # Verified accepted under `--strict-config`, which refuses keys codex
        # does not know — so a rename in a future release stops the run rather
        # than silently dropping the setting.
        argv += ["-c", f'model_reasoning_effort="{effort}"']
    argv.append(ticket)
    return argv


class CodexHarness:
    """One `codex exec` per investigation.

    A plain class rather than a frozen dataclass, because the JSONL it has read
    so far has to survive a cancellation — see `_pump`. One instance serves one
    ticket at a time, which is what the employee's single slot already
    guarantees.
    """

    name = "codex"

    def __init__(
        self,
        desk: Desk,
        env: dict[str, str],
        model: str = "",
        effort: str = "",
        timeout_s: float = 300.0,
    ) -> None:
        self._desk = desk
        self._env = env
        self._model = model
        self._effort = effort
        self._lines: list[str] = []
        self._timeout = timeout_s

    async def investigate(
        self,
        ticket: str,
        workdir: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> Outcome:
        self._lines = []
        # **The desk is laid out here, by the driver that has one.** It used to
        # be done by each agent's own service, one line before the loop was
        # called; when that service moved into the shared package the call had
        # nowhere to go — `run.investigate` knows nothing about desks, correctly
        # — and it was simply lost. Nothing failed loudly: the loop started in
        # an empty directory with no skills, no brief and no certificate, and
        # reported an investigation that had nothing to investigate with.
        prepare(self._desk, workdir)
        # Beside the workspace, not inside it. Both files used to sit in the
        # directory the sandbox lets the model write, and `investigate` treats
        # "the file exists" as "codex produced an answer" — so an agent could
        # write `answer.json` itself and have its scratch file returned as the
        # harness's verdict, past a run that exited non-zero. The one failure
        # the instrument could not see.
        outside = workdir.parent / "contract"
        outside.mkdir(parents=True, exist_ok=True)
        schema = outside / "answer.schema.json"
        schema.write_text(json.dumps(ANSWER_SCHEMA))
        last = outside / "answer.json"

        argv = build_argv(self._desk, schema, last, self._model, ticket, self._effort)

        try:
            stdout, stderr, code = await self._run(argv, workdir, on_step)
        except TimeoutError:
            events = _events("".join(self._lines))
            return Outcome(
                steps=[step for event in events for step in _steps(event)],
                usage=_usage(events),
                harness=self.name,
                error=f"codex did not finish within {self._timeout:.0f}s",
            )

        events = _events(stdout)
        steps = [step for event in events for step in _steps(event)]
        usage = _usage(events)
        if not last.is_file():
            return Outcome(
                steps=steps,
                usage=usage,
                harness=self.name,
                error=(
                    f"codex exited {code} without an answer: {stderr[-400:].strip()}"
                ),
            )
        if code:
            # Previously discarded whenever the file existed. codex exiting
            # non-zero after writing an answer is a failed run, and reporting it
            # as clean is how a broken investigation reads as a good one.
            return Outcome(
                steps=steps, usage=usage, harness=self.name,
                error=f"codex exited {code}: {stderr[-400:].strip()}",
            )
        return Outcome(
            answer=json.loads(last.read_text()),
            steps=steps,
            usage=usage,
            harness=self.name,
        )

    async def _run(
        self,
        argv: list[str],
        cwd: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> tuple[str, str, int | None]:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            # 8 MiB, because a JSONL line carries a whole command's output and
            # asyncio's StreamReader defaults to 64 KiB per line. Past that it
            # raises `Separator is not found, and chunk exceed the limit` and
            # the run dies outright — one shop query returning 115 KB killed a
            # campaign cell in zero seconds. `communicate()` had no such limit;
            # this is the price of reading the stream live, and it is only a
            # price if you forget to pay it.
            limit=8 * 1024 * 1024,
            # Its own process group, so the kill below reaches the shells codex
            # spawned and not merely codex. Without it the sandboxed commands
            # outlive the loop that started them.
            start_new_session=True,
            # The employee's own settings stay out of it; only what the role is
            # given to reach the company goes in.
            env=self._env,
            # Closed, not inherited. See the module docstring.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                self._pump(process, on_step), timeout=self._timeout
            )
        finally:
            # `finally`, not `except TimeoutError`. `CancelledError` is a
            # `BaseException` and slipped straight past the old handler, so a
            # Ctrl-C or a cancelled slot left codex running: the deadline lives
            # in the event loop that just died, and the subprocess never hears
            # about it. One orphan was measured at 90 minutes, and twelve run
            # directories here hold a prepared workspace and no record at all.
            await self._reap(process)
        return out, err, process.returncode

    @staticmethod
    async def _reap(process: asyncio.subprocess.Process) -> None:
        """Signal the whole group, then insist.

        TERM first so codex can close its own children; KILL only if it will
        not go. Both suppress `ProcessLookupError`, which is the ordinary race
        of the process having exited between the check and the signal.
        """
        if process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def _pump(
        self,
        process: asyncio.subprocess.Process,
        on_step: Callable[[Step], None] | None,
    ) -> tuple[str, str]:
        """Read the turn line by line as it happens, instead of at the end.

        `communicate()` is simpler and hands back everything once the process
        exits, which is fine for a record and useless for watching. codex writes
        each event as it occurs: timed from a run, `turn.started` arrives at
        0.1s and the command that follows at 11.6s. Reading the stream is what
        turns those into something a subscriber can see while it is happening.

        A failing callback must not fail the run. Publishing is somebody else's
        concern, and an investigation that dies because a watcher went away has
        the dependency backwards.
        """
        assert process.stdout is not None and process.stderr is not None
        # Accumulated on the instance, not in a local, so the timeout path can
        # still report the turn. `asyncio.wait_for` cancels this coroutine and
        # discards its frame, so a local list died with it: a run that executed
        # two hundred commands and hit the wall recorded `steps: []` — the exact
        # shape of "an investigation that did nothing", which is what cost a
        # grade on the opencode side this morning.
        lines = self._lines
        async for raw in process.stdout:
            line = raw.decode(errors="replace")
            lines.append(line)
            if on_step is None:
                continue
            try:
                # `_steps`, not `_step`: a watcher and the record must see
                # the same run. Narrating one step where the record keeps
                # two would make a trace read on the page disagree with the
                # trace a grader reads, which is the one thing this whole
                # translation layer exists to prevent.
                for step in _steps(json.loads(line)):
                    on_step(step)
            except Exception:  # noqa: BLE001
                continue
        err = (await process.stderr.read()).decode(errors="replace")
        await process.wait()
        return "".join(lines), err


CODEX_KINDS: dict[str, Kind] = {
    "thread.started": Kind.STARTED,
    "turn.started": Kind.THINKING,
    "turn.completed": Kind.FINISHED,
    "turn.failed": Kind.ERROR,
    "error": Kind.ERROR,
    "reasoning": Kind.THINKING,
    "agent_message": Kind.MESSAGE,
    "command_execution": Kind.COMMAND,
    "file_change": Kind.TOOL,
    "mcp_tool_call": Kind.TOOL,
    "web_search": Kind.TOOL,
    "todo_list": Kind.TOOL,
}
"""codex's vocabulary, mapped into the standard one.

Item types win over envelope types because an item is the specific thing that
happened; `item.completed` on its own says only that something finished.
"""


def _step(event: dict[str, Any]) -> Step:
    """One codex JSONL line, as a standard step.

    The vendor's shape stops here. An unmapped type still arrives, as `OTHER`
    with its native name attached: a codex release that adds an item type should
    show up in the stream rather than vanish inside this function.
    """
    item = event.get("item") or {}
    # `item["type"]`, not `item["item_type"]`. Guessed wrong once, and the unit
    # test guessed the same way, so both agreed and neither was right. The shape
    # came from a persisted record in the end.
    native = str(item.get("type") or event.get("type") or "")
    output = str(item.get("aggregated_output") or "")
    kind = CODEX_KINDS.get(native, Kind.OTHER)
    # A finished command carries its output; that is worth its own step rather
    # than being folded into the command that produced it.
    #
    # Keyed on the phase, **not on whether there is anything to show**. It used
    # to require non-empty output, so a command that succeeded silently — a
    # `mkdir`, a `cd`, a grep that matched nothing — stayed a second COMMAND
    # step, and the record opened a call that nothing ever closed. Two entries
    # for one command, one of them a phantom. 2 of 41 completed commands in the
    # persisted corpus.
    if kind is Kind.COMMAND and event.get("type") == "item.completed":
        kind = Kind.OUTPUT
        # A command that exited non-zero is a refusal, a 401, a missing binary —
        # not a result. 24 of 268 completed commands in the persisted corpus
        # exited non-zero and every one was published as a plain output, so a
        # `curl` that 401'd and a `curl` that returned the orders were the same
        # event to everything downstream, the judge included.
        if int(item.get("exit_code") or 0) != 0:
            kind = Kind.ERROR
    return Step(
        kind=kind,
        native=native,
        text=str(item.get("text") or output),
        # codex names its non-shell work by item type — `file_change`,
        # `web_search` — and carries no argument shape stable enough to fill
        # `args` from. So the type is the tool's name and the arguments stay
        # empty rather than invented; without this every one of them reached a
        # record called `tool`.
        tool=native if kind is Kind.TOOL else "",
        command=str(item.get("command") or ""),
    )


def _steps(event: dict[str, Any]) -> list[Step]:
    """One codex line, as the step or steps it really is.

    Almost always one. The exception is codex's **non-shell** work — a
    `file_change`, a `web_search` — which arrives as a single `item.completed`
    carrying both that the call was made and that it finished. Mapped to one
    `TOOL` step, it opened a call in the record that nothing ever closed, and
    every one of them was filed as unfinished: four of twenty-five calls in a
    real run, all of them work codex had in fact completed. A shell command gets
    two events and so gets two steps; this gives the others the same shape.
    """
    step = _step(event)
    if step.kind is not Kind.TOOL or event.get("type") != "item.completed":
        return [step]
    return [step, Step(kind=Kind.OUTPUT, native=step.native, text=step.text)]


def _events(stdout: str) -> list[dict[str, Any]]:
    """The JSONL turn, with unparseable lines dropped rather than fatal.

    A line this driver cannot read is a codex version that grew an event type,
    which must not cost an answer that already arrived.
    """
    steps: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            steps.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return steps


def _usage(events: list[dict[str, Any]]) -> Usage:
    """What the turn spent, as codex reported it on `turn.completed`.

    Counted by the driver that knows the vendor rather than by a shared layer
    above it. Without it a campaign's cost tables are blank, and those tables
    carry one of the lab's firmest findings: two analysts reaching the same
    diagnosis seventeen token-fold apart.

    **`input_tokens` INCLUDES its cached subset here**, which is codex's own
    convention and not opencode's — that side reports `total = input + output +
    cache.read`, with `input` excluding the cache. Left unreconciled, one column
    held two different quantities and a campaign compared a cache-inclusive
    figure against a cache-exclusive one, a ~7x difference on a real record.
    Both drivers normalise to "everything sent", with the cached part reported
    separately.

    `model_requests` stays at zero. codex says what a turn cost and never how
    many requests it took to spend it; counting turns instead would report `1`
    for an investigation that called the model forty times, and a figure this
    file invented is a figure the lab could publish wrong.
    """
    for event in events:
        usage = event.get("usage")
        if isinstance(usage, dict):
            return Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                reasoning_tokens=int(usage.get("reasoning_output_tokens") or 0),
                cache_read_tokens=int(usage.get("cached_input_tokens") or 0),
            )
    return Usage()
