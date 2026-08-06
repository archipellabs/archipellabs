"""The third driver, on the parts that do not need a model.

Two things earn a test here and neither can be reached from an employee's suite
without spending a model call: what a tool *result* becomes, and what a crashed
run reports it spent.

The first is the one that has bitten before. `record.from_steps` decides a call
failed only because the step closing it says so, and a fought run recorded as a
clean one is exactly the shape that made a judge grade an answer built on
evidence the loop was never allowed to gather.
"""

import pathlib

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolReturnPart,
)
from pydantic_ai.usage import RequestUsage

from core.config import (
    Config,
    FeedConfig,
    LokiConfig,
    MatomoConfig,
    ModelConfig,
    QueueConfig,
    ShopConfig,
)
from core.harness.base import Kind
from core.harness.pydantic_ai import (
    PydanticAiHarness,
    Toolbox,
    _returned,
    build,
    counted,
    run_of,
)
from core.record import from_steps


def config(api: str = "chat") -> Config:
    """A deployment with only the fields this driver reads set."""
    return Config(
        model=ModelConfig(name="a-model", base_url="", api_key="", api=api),
        shop=ShopConfig(base_url="", api_key="", timezone="UTC"),
        matomo=MatomoConfig(base_url="", token="", site_id="1"),
        loki=LokiConfig(base_url=""),
        queue=QueueConfig(url="", namespace=""),
        feed=FeedConfig(host="", port=22, user="", password="", directory=""),
    )


def test_it_builds_the_loop_it_names() -> None:
    box: Toolbox[None] = Toolbox(
        deps_type=type(None),
        deps=lambda _config, _workdir: pytest.fail("not opened here"),
        register=lambda _agent: None,
    )

    assert isinstance(build(config(), box), PydanticAiHarness)


def test_a_tool_return_is_the_text_the_model_received() -> None:
    """Not `str()` of the Python object the tool returned: a run's context is
    the sum of these, resent whole on every later turn, and the two lengths are
    not the same number."""
    step = _returned(
        ToolReturnPart(tool_name="shop_get", content={"orders": [1, 2, 3]}), None, "c1"
    )

    assert step.kind is Kind.OUTPUT
    assert step.tool == "shop_get"
    # The JSON that was sent, not `"{'orders': [1, 2, 3]}"`.
    assert step.text == '{"orders":[1,2,3]}'


def test_a_retry_is_an_error_rather_than_a_result() -> None:
    """pydantic-ai answers a tool that raised, or arguments that failed
    validation, by telling the model to try again. Recorded as a plain result, a
    fought run reads as a clean one."""
    step = _returned(
        RetryPromptPart(content="field required", tool_name="thought"), None, "c1"
    )

    assert step.kind is Kind.ERROR
    assert step.tool == "thought"
    assert "field required" in step.text


def test_a_failed_call_is_marked_on_the_call_it_belongs_to() -> None:
    """A judge counting successful reads must not count a refusal among them,
    and a sibling entry of its own would both hide the failure and inflate the
    call count the report publishes."""
    steps = [
        _returned(ToolReturnPart(tool_name="shop_get", content="ok"), None, "a"),
        _returned(
            ToolReturnPart(tool_name="logs_query", content="denied", outcome="failed"),
            None,
            "b",
        ),
    ]

    calls = from_steps(steps)

    assert [call.status for call in calls] == ["completed", "error"]


def test_a_call_reports_how_long_it_took() -> None:
    """The difference between "the run took ten minutes" and "the log store took
    nine of them"."""
    step = _returned(ToolReturnPart(tool_name="logs_query", content="[]"), 0.0, "c1")

    assert step.duration_ms is not None and step.duration_ms >= 0


def test_a_crashed_run_is_counted_from_the_messages_it_left() -> None:
    """`result.usage` does not exist on the crash path, and a run killed by a
    per-minute token limit is the one you most want a token count for — it was
    the only outcome that reported none."""
    messages = [
        ModelRequest(parts=[]),
        ModelResponse(
            parts=[TextPart(content="thinking")],
            usage=RequestUsage(
                input_tokens=100,
                output_tokens=10,
                cache_read_tokens=40,
                details={"reasoning_tokens": 7},
            ),
        ),
        ModelResponse(
            parts=[TextPart(content="more")],
            usage=RequestUsage(input_tokens=200, output_tokens=20),
        ),
    ]

    spent = counted(messages)

    assert spent.model_requests == 2
    assert (spent.input_tokens, spent.output_tokens) == (300, 30)
    # Billed and invisible inside `output_tokens`; counted on one side only,
    # "both loops think at the same depth" is a setting rather than a reading.
    assert spent.reasoning_tokens == 7
    # Included in `input_tokens` here, as codex reports it and opencode does not.
    assert spent.cache_read_tokens == 40


def test_the_run_a_workspace_belongs_to_is_its_own_directory() -> None:
    """`<runs>/<run_id>/workspace`, so the transcript can be named after the run
    and an employee's scratch keyed by it."""
    assert run_of(pathlib.Path("/runs/angel_abc123/workspace")) == "angel_abc123"
