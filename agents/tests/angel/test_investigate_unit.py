"""The investigation core, with a scripted model and no network.

`run_investigation` is the shared path between the CLI and the queue action, so
what it returns IS the contract a caller sees. It had no test, and the gap cost
two live runs: the verdict envelope carries `run_id`, splatting it into the
narrator collided with the positional argument, and the run died at its final
step after ten minutes of real work. A `FunctionModel` reproduces that in
milliseconds.

The scripted model calls `thought` — the one tool needing no HTTP client — so
these exercise real tool-call plumbing without reaching the shop, Matomo or Loki.

**The loop moved to `core.harness.pydantic_ai` and the envelope to
`core.run`, and this file was kept.** Three things had to move with them:
the model is swapped at the driver's own build seam rather than at Angel's, the
narration is a `Narrator` object rather than a `sink` callable, and the verdict
is nested under `answer` rather than splatted flat beside the accounting. Every
assertion about what an investigation *does* is the one it always was.
"""

import json
import pathlib
from typing import Any

import pytest
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from core import investigate, record
from core.config import (
    Config,
    LokiConfig,
    MatomoConfig,
    ModelConfig,
    QueueConfig,
    ShopConfig,
)
from core.harness import pydantic_ai as driver
from roles.angel.identity import IDENTITY
from roles.angel.investigate import run_investigation

VERDICT = {
    "detected": "Canadian checkouts fail",
    "diagnosis": "no delivery row for the Canada zone",
    "root_cause": "the CA line left the carrier feed at 20:28",
    "remediation": "restore the CA row in carriers.csv",
    "confidence": "high",
    "findings": [{"fact": "0 Canadian orders since 20:28", "source": "shop"}],
}


@pytest.fixture
def cfg(tmp_path, monkeypatch) -> Config:
    """A config that points nowhere. Nothing here should open a socket."""
    from core.config import FeedConfig

    # Set rather than deleted: `record.runs_dir()` reads this per call, so the
    # run's workspace, its record and its transcript all land under the test's
    # own tmp instead of in the employee's `runs/`.
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path))
    return Config(
        model=ModelConfig(name="scripted", base_url="http://nowhere/v1", api_key="k"),
        shop=ShopConfig(
            base_url="http://nowhere", api_key="k", timezone="America/Chicago"
        ),
        matomo=MatomoConfig(base_url="http://nowhere", token="t", site_id="1"),
        loki=LokiConfig(base_url="http://nowhere"),
        queue=QueueConfig(url="redis://nowhere", namespace="test"),
        feed=FeedConfig(host="h", port=22, user="u", password="p", directory="/d"),
    )


class Heard:
    """A narrator that keeps what it was told, in order.

    What a subscriber gets. It used to be a `sink(event, fields)` callable; the
    shared loop publishes through the `Narrator` protocol now, so the three
    boundaries are three methods and a step's kind is the standard word rather
    than the vendor's `tool_called`.
    """

    def __init__(self) -> None:
        self.said: list[tuple[str, dict[str, Any]]] = []

    async def started(self, **fields: Any) -> None:
        self.said.append(("started", fields))

    async def step(self, **fields: Any) -> None:
        self.said.append(("step", fields))

    async def finished(self, **fields: Any) -> None:
        self.said.append(("finished", fields))

    def kinds(self) -> list[str]:
        return [fields["kind"] for name, fields in self.said if name == "step"]

    def of(self, boundary: str) -> list[dict[str, Any]]:
        return [fields for name, fields in self.said if name == boundary]


def _tool_calls_so_far(messages: list[Any]) -> int:
    return sum(
        1
        for message in messages
        for part in message.parts
        if getattr(part, "part_kind", "") == "tool-call"
    )


def script(monkeypatch, *, plan) -> None:
    """Give the analyst a scripted model, keeping every real tool registration.

    Streamed, not the plain response form: the driver passes an
    `event_stream_handler` to narrate live, which puts pydantic-ai into streamed
    mode. A non-streaming fake would test a code path the real one never takes.

    `plan(count)` returns `(tool_name, args)` to call next, or raises to
    simulate the model dying mid-loop.

    Patched at the **driver's** seam rather than at Angel's, because assembling
    the agent is the driver's job now. `build_agent` is looked up on the module
    when a run starts, so replacing it here reaches the run — and Angel's real
    `Toolbox` still registers every real tool.
    """
    real_build = driver.build_agent

    async def stream(messages: list[Any], info: AgentInfo) -> Any:
        name, args = plan(_tool_calls_so_far(messages))
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(args))}

    def build_with_script(cfg: Any, toolbox: Any) -> Any:
        built = real_build(cfg, toolbox)
        built.model = FunctionModel(stream_function=stream)
        return built

    monkeypatch.setattr(driver, "build_agent", build_with_script)


def thinks_then_concludes(count: int) -> tuple[str, dict[str, Any]]:
    """Two `thought` calls — the one tool needing no HTTP — then the verdict."""
    if count < 2:
        return "thought", {"thought": "checking"}
    return "final_result_Answer", VERDICT


async def test_a_completed_run_returns_the_verdict_and_its_provenance(cfg, monkeypatch):
    script(monkeypatch, plan=thinks_then_concludes)

    verdict = await run_investigation(cfg, "sales look off")

    assert verdict["status"] == "completed"
    assert verdict["answer"]["detected"] == VERDICT["detected"]
    assert verdict["answer"]["remediation"] == VERDICT["remediation"]
    assert verdict["run_id"].startswith("angel_")
    assert verdict["duration_ms"] >= 0


async def test_both_artifacts_are_written_and_the_record_is_the_one_pointed_at(
    cfg, monkeypatch, tmp_path
):
    """The verdict is a summary; the transcript is the artifact a grade reads.

    Two files, one run. The **record** is what `transcript` names, because every
    employee writes that shape and a grader with one reader cannot report a
    figure that depends on which lineage a row came from. The verbatim message
    dump is still written — it holds the system prompt, the reasoning and each
    retry, which is what a person wants when a run went wrong — it is simply no
    longer the graded one.
    """
    script(monkeypatch, plan=thinks_then_concludes)

    verdict = await run_investigation(cfg, "sales look off")

    assert (tmp_path / f"{verdict['run_id']}.json").is_file(), "the verbatim dump"
    assert (tmp_path / f"{verdict['run_id']}.record.json").is_file(), "the record"
    assert verdict["transcript"].endswith(f"{verdict['run_id']}.record.json")


async def test_tool_calls_exclude_the_reporting_call(cfg, monkeypatch):
    """`final_result_*` is how the agent reports, not part of the investigation.
    Counting it inflates every run by one."""
    script(monkeypatch, plan=thinks_then_concludes)

    verdict = await run_investigation(cfg, "sales look off")

    assert verdict["tool_calls"] == 2


async def test_the_sink_sees_the_whole_run_live(cfg, monkeypatch):
    """What a queue subscriber gets: a start, each tool as it happens, a verdict."""
    heard = Heard()

    script(monkeypatch, plan=thinks_then_concludes)
    await investigate(IDENTITY, cfg, "sales look off", narrator=heard)

    boundaries = [name for name, _ in heard.said]
    assert boundaries[0] == "started"
    assert boundaries[-1] == "finished"
    assert heard.kinds().count("tool") == 2
    assert heard.kinds().count("output") == 2


async def test_a_refusal_is_reported_as_failed_not_crashed(cfg, monkeypatch):
    """The agent's own `Refusal` output — it looked, and could not do the job.
    Distinct from the harness breaking underneath it.

    `checked` is the refusal's own field and no longer reaches the caller: the
    shared envelope carries a status and a reason, the same two for every loop.
    It is in the transcript, which is what a grade reads.
    """

    def refuses(count: int) -> tuple[str, dict[str, Any]]:
        return "final_result_Refusal", {
            "error": "no analytics access",
            "checked": ["shop"],
        }

    script(monkeypatch, plan=refuses)

    verdict = await run_investigation(cfg, "sales look off")

    assert verdict["status"] == "failed"
    assert verdict["error"] == "no analytics access"
    assert "no analytics access" in pathlib.Path(verdict["transcript"]).read_text()


async def test_plain_text_from_the_model_is_never_a_completed_verdict(cfg, monkeypatch):
    """Some models answer in prose instead of calling the output tool — a real
    failure mode here, twice. It must not be dressed up as a diagnosis."""
    real_build = driver.build_agent

    async def chats(messages: list[Any], info: AgentInfo) -> Any:
        yield "I think it is the carriers."

    def build_with_prose(cfg_: Any, toolbox: Any) -> Any:
        built = real_build(cfg_, toolbox)
        built.model = FunctionModel(stream_function=chats)
        return built

    monkeypatch.setattr(driver, "build_agent", build_with_prose)

    verdict = await run_investigation(cfg, "sales look off")

    assert verdict["status"] != "completed"


async def test_an_empty_thought_is_accepted_rather_than_killing_the_run(
    cfg, monkeypatch
):
    """Two of three runs in a campaign died here. Gemma-class models emit
    reasoning as a tool call and sometimes send no arguments at all; with
    `thought` required, pydantic rejected "field required" twice and the run was
    terminated at its fourth call having investigated nothing. The tool exists to
    absorb that habit, so it must absorb the empty case too."""

    def empty_thought_then_conclude(count: int) -> tuple[str, dict[str, Any]]:
        if count < 2:
            return "thought", {}
        return "final_result_Answer", VERDICT

    script(monkeypatch, plan=empty_thought_then_conclude)

    verdict = await run_investigation(cfg, "sales look off")

    assert verdict["status"] == "completed"
    assert verdict["tool_calls"] == 2


async def test_each_tool_call_reports_its_own_latency_and_size(
    cfg, monkeypatch, tmp_path
):
    """A ten-minute run is one number with no way to say whether the shop, Loki
    or the model was slow. Per-call timing is what makes that answerable, and
    the size that goes back to the model is what a run's context is the sum of —
    resent whole on every later turn.

    Latency reaches a subscriber live; the size is in the record, where a call
    and its result are one entry. They used to be two fields of one event."""
    heard = Heard()

    script(monkeypatch, plan=thinks_then_concludes)
    verdict = await investigate(IDENTITY, cfg, "sales look off", narrator=heard)

    returned = [fields for fields in heard.of("step") if fields["kind"] == "output"]
    assert returned, "a tool return must reach the subscriber"
    for fields in returned:
        assert isinstance(fields["duration_ms"], int)
        assert fields["duration_ms"] >= 0

    calls = record.read(tmp_path / f"{verdict['run_id']}.record.json").calls
    assert calls
    # These returns are far shorter than the storage cap, so the recorded size
    # and the stored output agree. They part company once a result is clipped —
    # which is the case the field exists for.
    assert all(call.output_chars == len(call.output) for call in calls)
