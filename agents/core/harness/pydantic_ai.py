"""The pydantic-ai loop, driven inside this process.

The other two drivers start a program and read what it prints. This one *is* the
loop: the model is called from here, the tools are Python functions in this
interpreter, and the verdict comes back as a typed object rather than as prose
with a JSON blob somewhere in it. That is the difference the lab is measuring,
so it is worth stating plainly rather than hiding behind a shared interface.

What that buys, and what it costs:

* **The answer cannot be malformed.** `output_type=[Answer, Refusal]` makes the
  verdict a tool the model must satisfy, and pydantic-ai retries the model until
  it does. The loops that ask for a shape in words check it on the way out
  instead.
* **The steps are subscribed to, not parsed.** pydantic-ai raises typed events
  while the run happens, so `Step`s are produced live and a ten-minute
  investigation is watchable. There is no stream to re-read afterwards.
* **A crash leaves nothing behind unless it is caught.** A subprocess writes its
  JSONL whatever happens to the parent; here the conversation lives in memory,
  which is why `capture_run_messages` wraps every run. A run killed by a
  per-minute token limit is the one you most want a token count for, and it was
  the only outcome that reported none.

The only per-agent part is a `Toolbox`: what the employee can reach, and the
clients those tools need. Everything else below was copied identically in two
employees, and each comment in it records something that went wrong once.
"""

import pathlib
import time
from collections.abc import AsyncIterable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.agent import AgentRunResult, EventStreamHandler
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelMessagesTypeAdapter,
    RetryPromptPart,
    ToolReturnPart,
)
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from core import record
from core.brief import BRIEF
from core.config import Config
from core.contract import Answer, Refusal
from core.harness.base import Harness, Kind, Outcome, Step, Usage

HARNESS = "pydantic-ai"
"""What a record calls this loop.

The library's name rather than the employee's: two employees run on it, and a
table grouping by harness must put them in the same row."""

MODEL_MAX_RETRIES = 8
"""How many times the transport retries a throttled request.

Only 429s and connection errors — the SDK does not retry a refusal or a bad
request. Eight is generous because the cost of giving up is an entire
investigation, and the cost of waiting is a few seconds."""

SYSTEM_PROMPT = BRIEF
"""The shared brief, and nothing added to it.

Unlike the opencode drivers, which must also ask for the answer's SHAPE in
words: here the shape is a type the model is held to, so there is nothing to
say about it. Four employees carrying four wordings would compare wordings."""


@dataclass(frozen=True)
class Toolbox[DepsT]:
    """One employee's tools, and the clients they need — the only per-agent part.

    Three callables rather than one object, because they happen at three
    different times: the type is needed to build the agent, the clients when a
    ticket arrives, and the registrations once per agent. An employee that
    handed over a live `Deps` instead would have to open its HTTP connections
    before knowing whether there was any work, and close them somewhere else.
    """

    deps_type: type[DepsT]
    """The dataclass pydantic-ai type-checks every tool's `RunContext` against."""
    deps: Callable[[Config, pathlib.Path], AbstractAsyncContextManager[DepsT]]
    """This run's clients, opened and closed around one investigation.

    Given the workdir as well as the configuration, so an employee that keeps
    per-run scratch can bind it in the same `async with` that opens the clients
    — see `run_of`. It used to be a `try/finally` in each employee's own copy of
    the loop, which is exactly the code this driver exists to have once."""
    register: Callable[[Agent[DepsT, Answer | Refusal]], None]
    """Attaches the employee's `@agent.tool` closures. Called once per run,
    because the agent is built per run: a change of model or depth takes effect
    on the next ticket rather than on the next restart."""
    request_limit: int = 120
    """Model requests one investigation may spend.

    pydantic-ai defaults to 50, which was enough when the tools handed over
    pre-joined answers and is not now: reading a resource's fields, then
    querying it, then joining it to another is several calls where there used to
    be one. High enough that a real investigation finishes, low enough that a
    model stuck in a loop stops instead of running all night."""


def build[DepsT](config: Config, toolbox: Toolbox[DepsT]) -> Harness:
    """The pydantic-ai loop, as one employee's tools describe it.

    The toolbox is passed rather than found, exactly as the desk and the MCP
    server are on the other drivers: what an employee can reach is the boundary
    this lab varies, and this driver is shared by all of them.
    """
    return PydanticAiHarness(config=config, toolbox=toolbox)


def build_agent[DepsT](
    config: Config, toolbox: Toolbox[DepsT]
) -> Agent[DepsT, Answer | Refusal]:
    """The agent itself, assembled where it can be read and tested.

    Separated from the run for the same reason `codex.build_argv` is: everything
    here is a decision that cost a debugging round, and a test can build one
    without spending a model call.
    """
    # A hosted model answers a long investigation with 429s: each turn resends
    # the whole conversation, so a single late request can exceed a per-minute
    # token budget on its own. The reply says "try again in 2.6s" — a throttle,
    # not a failure — and letting it end an eight-minute run threw away 25 tool
    # calls of real work twice. The SDK honours Retry-After when told to retry.
    provider = OpenAIProvider(
        openai_client=AsyncOpenAI(
            base_url=config.model.base_url,
            api_key=config.model.api_key,
            max_retries=MODEL_MAX_RETRIES,
        )
    )
    # Same provider, two HTTP surfaces. Reasoning models refuse function tools on
    # /v1/chat/completions and require /v1/responses; local servers speak chat.
    # Chosen by configuration rather than by sniffing the model name, so adding a
    # model stays a matter of environment variables.
    model = (
        OpenAIResponsesModel(config.model.name, provider=provider)
        if config.model.api == "responses"
        else OpenAIChatModel(config.model.name, provider=provider)
    )
    agent: Agent[DepsT, Answer | Refusal] = Agent(
        model,
        deps_type=toolbox.deps_type,
        # A sequence, not the union itself: pydantic-ai turns each member into a
        # separate output tool, so the model picks "answer" or "refusal" by
        # calling one rather than by filling in a discriminator it cannot see.
        output_type=[Answer, Refusal],
        system_prompt=SYSTEM_PROMPT,
        retries=2,
        # Pinned, not left to the API default. Unset, pydantic-ai sent nothing
        # while opencode sent reasoning parameters of its own, so the two
        # harnesses were thinking at different depths and the gap would have
        # been read as a property of the harness. `medium` is the floor.
        model_settings=OpenAIResponsesModelSettings(
            openai_reasoning_effort=config.model.reasoning  # type: ignore[typeddict-item]
        )
        if config.model.api == "responses"
        else None,
    )
    toolbox.register(agent)
    return agent


def run_of(workdir: pathlib.Path) -> str:
    """Which run this workspace belongs to.

    `run.investigate` lays out `<runs>/<run_id>/workspace` and hands over the
    inner directory, so the run's own name is the directory above it. Derived in
    one place because two things need it and neither is given it: the verbatim
    transcript, which is named after the run, and an employee's per-run scratch,
    which is keyed by it.
    """
    return workdir.parent.name


class PydanticAiHarness[DepsT]:
    """One agent run per investigation.

    Generic in the deps, so an employee's tools keep their own type all the way
    from `Toolbox` to `RunContext[Deps]`. Erased to `Any`, every tool signature
    in both employees would be unchecked — which is most of what these employees
    are made of.
    """

    name = HARNESS

    def __init__(self, config: Config, toolbox: Toolbox[DepsT]) -> None:
        self._config = config
        self._toolbox = toolbox

    async def investigate(
        self,
        ticket: str,
        workdir: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> Outcome:
        """Run once, with this employee's clients open for exactly that long.

        **Returns, never raises.** A rate limit, a refused key or a model that
        will not stop talking are outcomes to record, not exceptions to hand to
        whoever asked: the caller wants the transcript path either way.

        `workdir` **names** the run rather than holding it, which is worth saying
        out loud. A desk is laid out in the directory it is given; these
        employees have no shell and their tools keep scratch of their own, so
        what this driver takes from it is the run's identity — see `run_of` —
        and it is handed on to `deps` for the same reason.
        """
        steps: list[Step] = []

        def happen(step: Step) -> None:
            steps.append(step)
            if on_step is not None:
                on_step(step)

        # The clients and the employee's scratch are bound together, and both
        # released before this returns. A `finally` in each employee's own loop
        # did this twice, differently.
        async with self._toolbox.deps(self._config, workdir) as deps:
            agent = build_agent(self._config, self._toolbox)
            # The conversation lives in memory, so a run that raises has nothing
            # to re-read afterwards unless it was being captured all along.
            with capture_run_messages() as messages:
                try:
                    result = await agent.run(
                        ticket,
                        deps=deps,
                        usage_limits=UsageLimits(
                            request_limit=self._toolbox.request_limit
                        ),
                        event_stream_handler=_narrating(happen),
                    )
                except Exception as error:  # noqa: BLE001 — a dead loop is a result
                    return Outcome(
                        steps=steps,
                        # Counted from the captured messages, because `result`
                        # never existed. A run killed by a per-minute token
                        # limit is the one you most want a token count for, and
                        # it was the only outcome that reported none.
                        usage=counted(messages),
                        harness=self.name,
                        error=f"{type(error).__name__}: {error}",
                    )
                finally:
                    # Written on both paths, and on the crash path especially:
                    # a run that died after twenty tool calls is the one whose
                    # messages somebody will actually read.
                    keep(workdir, messages)

        return _outcome(result, steps)


def _outcome(
    result: AgentRunResult[Answer | Refusal],
    steps: list[Step],
) -> Outcome:
    """What the loop concluded, as the neutral shape.

    A `Refusal` travels as the answer *and* as the error, which is the one thing
    here worth reading twice. `run._settle` calls an outcome with an error and
    nothing else a **crash**, and an analyst that looked and honestly could not
    conclude is not a broken harness — scored as the same zero, the lab cannot
    tell the two apart. Carrying the refusal in `answer` is what makes it a
    `failed` run whose reason is the analyst's own words.
    """
    output = result.output
    refused = output.error if isinstance(output, Refusal) else None
    return Outcome(
        answer=output.model_dump(),
        steps=steps,
        usage=spent(result),
        harness=HARNESS,
        error=refused,
    )


# ── the run, as standard steps ───────────────────────────────────────────────


def _narrating(happen: Callable[[Step], None]) -> EventStreamHandler[Any]:
    """An event handler that reports each tool call as it happens.

    The alternative — replaying the messages once the run is over — is still how
    the transcript is written, because reading messages cannot perturb a run.
    But a subscriber watching a ten-minute investigation wants to see it
    working, and a run that dies mid-way has already said what it was doing.

    `happen` is synchronous, like every driver's `on_step`. It is called
    straight from inside this async handler rather than awaited or scheduled: a
    step that reaches nobody is not an error, and an investigation must not be
    able to fall behind its own commentary.
    """
    # When each call started, by tool_call_id. A tool's latency is the gap
    # between its call and its result, and without it a slow run is a single
    # number with no way to say whether the shop, Loki or the model was slow —
    # which is exactly the question a ten-minute local-model run raises.
    started_at: dict[str, float] = {}

    async def handler(
        _ctx: Any, stream: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for event in stream:
            # The output tools — `final_result_Answer` and its sibling — arrive
            # as `OutputToolCallEvent`, a different type, and are deliberately
            # not translated. Reporting the verdict is how the loop finishes,
            # not part of the investigation, and counting it inflates every run
            # by one call it never made.
            if isinstance(event, FunctionToolCallEvent):
                started_at[event.tool_call_id] = time.monotonic()
                happen(
                    Step(
                        kind=Kind.TOOL,
                        native="tool_called",
                        tool=event.part.tool_name,
                        # The arguments as the model passed them, structured.
                        # Flattened to a string here once, they reached the
                        # record as `{"command": "..."}` — the one thing a named
                        # call never had.
                        args=event.part.args_as_dict(),
                        # **This loop is the reason `call_id` exists.** It runs a
                        # turn's calls concurrently and emits each result as it
                        # completes, so results do not arrive in the order the
                        # calls were made. Without the id the record pairs by
                        # position: the slower call gets no output and the
                        # faster result is attributed to a call nobody made.
                        call_id=event.tool_call_id,
                    )
                )
            elif isinstance(event, FunctionToolResultEvent):
                began = started_at.pop(event.tool_call_id, None)
                happen(_returned(event.part, began, event.tool_call_id))

    return handler


def _returned(
    part: ToolReturnPart | RetryPromptPart, began: float | None, call_id: str
) -> Step:
    """One tool result, as the step the record will pair with its call.

    **A retry is an `ERROR`, not an output.** pydantic-ai answers a tool that
    raised `ModelRetry`, or arguments that failed validation, with a
    `RetryPromptPart` — the model is told to try again. Recorded as a plain
    result, a fought run reads as a clean one: `record.from_steps` marks a call
    `error` only when its closing step says so, and the grader reports that
    column as rejections.
    """
    elapsed = None if began is None else round((time.monotonic() - began) * 1000)
    if isinstance(part, RetryPromptPart):
        return Step(
            kind=Kind.ERROR,
            native="retry_prompt",
            tool=part.tool_name or "",
            text=part.model_response(),
            duration_ms=elapsed,
            call_id=call_id,
        )
    # `outcome` is pydantic-ai's own word for a tool that raised rather than
    # returned. Declared, not inferred: a record that decided by matching
    # `"error":` against the text would lie the first time a tool legitimately
    # returns a field of that name.
    return Step(
        kind=Kind.ERROR if part.outcome == "failed" else Kind.OUTPUT,
        native="tool_returned",
        tool=part.tool_name,
        # What the MODEL received, not what the tool returned as a Python
        # object. A run's context is the sum of these, resent whole on every
        # later turn, and `str(...)` of a dict is a different length from the
        # JSON that was actually sent.
        text=part.model_response_str(),
        duration_ms=elapsed,
        call_id=call_id,
    )


# ── what the run spent, and what it left behind ──────────────────────────────


def spent(result: AgentRunResult[Any]) -> Usage:
    """What a finished run cost, as pydantic-ai accumulated it.

    **`input_tokens` INCLUDES its cached subset**, which is this library's own
    convention and codex's, but not opencode's — that side reports `total =
    input + output + cache.read`. Left unreconciled, one column held two
    different quantities and a campaign compared a cache-inclusive figure
    against a cache-exclusive one, a ~7x difference on a real record.
    """
    return Usage(model_requests=result.usage.requests, **_tokens(result.usage))


def counted(messages: Sequence[ModelMessage]) -> Usage:
    """The same totals, summed from the messages themselves.

    A finished run reads them off `result.usage`; a crashed one has no result,
    and a run killed by a per-minute token limit is precisely the one whose
    token count you want. Three such runs were reported with no usage at all,
    which made a quota failure indistinguishable from a cheap one.

    Only responses carry usage — requests do not, and an older message may carry
    none — so one request is counted per message that has any, and anything
    absent counts as zero rather than breaking the envelope.
    """
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
    }
    requests = 0
    for message in messages:
        usage = getattr(message, "usage", None)
        if usage is None:
            continue
        requests += 1
        for name, value in _tokens(usage).items():
            totals[name] += value
    return Usage(model_requests=requests, **totals)


def _tokens(usage: Any) -> dict[str, int]:
    """The four counts, however this version of the library spells them.

    Reasoning tokens are billed and invisible inside `output_tokens`, and have
    been reported both as a field and inside `details` across releases. Counted
    on one side only, "both loops think at the same depth" becomes a setting
    rather than a measurement.
    """
    details = getattr(usage, "details", None) or {}
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "reasoning_tokens": (
            getattr(usage, "output_reasoning_tokens", 0)
            or details.get("reasoning_tokens", 0)
            or 0
        ),
        "cache_read_tokens": getattr(usage, "cache_read_tokens", 0) or 0,
    }


def keep(workdir: pathlib.Path, messages: Sequence[ModelMessage]) -> pathlib.Path:
    """Every message verbatim, beside the run's own record.

    The neutral record holds one entry per tool call and what it returned, and
    **that is what the envelope points at**. This holds everything else: the
    system prompt, the model's reasoning, each retry, and every tool's complete
    return. Too big for an event, and exactly what a person wants when a run
    went wrong and the summary does not explain why.

    Written and not pointed at, deliberately. It was the graded artifact until
    every employee wrote the neutral record, and one lineage keeping its own
    format meant the grader carried two readers and every figure depended on
    which one a row happened to take. The two were compared on a real run —
    same tool calls, same rejections, same repetitions, same tools in the same
    order — before this stopped being the one that counted.

    `<runs>/<run_id>.json`, beside `<run_id>.record.json`: two artifacts of one
    run, named the same way, which is where the campaign's re-grader looks.
    """
    directory = record.runs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_of(workdir)}.json"
    path.write_bytes(ModelMessagesTypeAdapter.dump_json(list(messages), indent=2))
    return path
