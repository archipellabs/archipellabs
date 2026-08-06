"""Blair reaching its own tools, with a scripted model and no network.

**One question, and it is the only one this file can answer.** It used to ask
three — does a completed run carry its provenance, does a subscriber see the
work live, does a dying model still report what it spent — which were Angel's
three, asked again here. All three are properties of the shared loop, and the
shared loop is now tested once in `core` against every employee at the
same time. Asked here too, they were the same assertion maintained twice and
able to disagree.

Worse, the scripted plan called `thought`, which is Angel's tool copied into
Blair with the rest of the toolset — so a suite named for Blair exercised
nothing that makes it Blair. It calls `table_list` now.
"""

import json
import pathlib
from typing import Any

import pytest
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from core import record
from core.config import (
    Config,
    FeedConfig,
    LokiConfig,
    MatomoConfig,
    ModelConfig,
    QueueConfig,
    ShopConfig,
)
from core.harness import pydantic_ai as driver
from roles.blair.investigate import run_investigation

VERDICT = {
    "detected": "A verified symptom",
    "diagnosis": "A verified mechanism",
    "root_cause": "The initiating event was not observable",
    "remediation": "Repair the named setting in the source system",
    "confidence": "medium",
    "findings": [{"fact": "12 affected records", "source": "shop_query"}],
}


@pytest.fixture
def cfg(tmp_path, monkeypatch) -> Config:
    # Read per call by `record.runs_dir()`, so the workspace, the record and the
    # transcript all land under the test's own tmp.
    monkeypatch.setenv("AGENT_TRANSCRIPT_DIR", str(tmp_path))
    return Config(
        ModelConfig("scripted", "http://nowhere/v1", "key"),
        ShopConfig("http://nowhere", "key", "America/Chicago"),
        MatomoConfig("http://nowhere", "token", "1"),
        LokiConfig("http://nowhere"),
        QueueConfig("redis://nowhere", "test"),
        FeedConfig("host", 22, "user", "pass", "/data"),
    )



def _calls(messages: list[Any]) -> int:
    return sum(
        part.part_kind == "tool-call"
        for message in messages
        for part in message.parts
    )


def scripted(monkeypatch, plan) -> None:
    real_build = driver.build_agent

    async def stream(messages: list[Any], info: AgentInfo) -> Any:
        name, args = plan(_calls(messages))
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(args))}

    def build_agent(cfg: Any, toolbox: Any) -> Any:
        result = real_build(cfg, toolbox)
        result.model = FunctionModel(stream_function=stream)
        return result

    monkeypatch.setattr(driver, "build_agent", build_agent)


def concludes(count: int) -> tuple[str, dict[str, Any]]:
    """One of **Blair's own** tools, then the verdict.

    It used to call `thought` twice — which is Angel's tool, copied into Blair
    along with the rest — so this suite exercised the shared loop and never
    touched anything that makes Blair Blair. `table_list` is the cheapest tool
    that is genuinely its own: local, no client, and registered from Blair's
    `tables` module rather than Angel's `data`.
    """
    if count < 1:
        return "table_list", {}
    return "final_result_Answer", VERDICT


async def test_a_run_reaches_blair_s_own_tools_and_comes_back_whole(cfg, monkeypatch):
    """The one thing this suite can say that `core`'s cannot: that **this**
    employee's toolbox registers, is reachable by the model, and produces an
    envelope wearing this employee's name.

    Everything else it used to assert — the envelope's shape, live narration, a
    crash reporting what it spent — is the shared loop's, and is asserted there
    against every employee at once rather than here against one.
    """
    scripted(monkeypatch, concludes)

    result = await run_investigation(cfg, "something is wrong")

    assert result["status"] == "completed"
    assert result["run_id"].startswith("blair_")
    assert result["tool_calls"] == 1
    assert result["answer"]["detected"] == VERDICT["detected"]
    # The neutral record, not the verbatim message dump. Both are written; the
    # record is the one every employee shares, so it is the one a grader reads.
    assert result["transcript"].endswith(f"{result['run_id']}.record.json")

    called = record.read(
        pathlib.Path(result["transcript"])
    ).calls
    assert [call.tool for call in called] == ["table_list"]
