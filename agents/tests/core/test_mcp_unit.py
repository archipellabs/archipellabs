"""The MCP-equipped opencode driver, without launching opencode.

Every case here is a bug that actually happened, and every one of them was found
by running a three-minute campaign and reading a record afterwards. Each cost
more than the test would have, which is the point of the file: the contract with
an external server is checkable in milliseconds.

These checks were written twice, once in each of the two employees that ran this
loop, against two byte-identical copies of a driver. They live with the driver
now, so a third employee equipped this way inherits them instead of copying them.
"""

import json
import pathlib

import httpx
import pytest

from core.brief import BRIEF, JSON_VERDICT
from core.config import (
    Config,
    FeedConfig,
    LokiConfig,
    MatomoConfig,
    ModelConfig,
    QueueConfig,
    ShopConfig,
)
from core.harness import opencode_mcp
from core.harness.base import Kind
from core.harness.opencode_api import Session, converse
from core.harness.opencode_mcp import (
    PROVIDER,
    SYSTEM_PROMPT,
    McpHarness,
    McpServer,
    server_config,
    steps,
)
from core.record import from_steps

TOOLS = McpServer(
    command=["uv", "run", "python", "-m", "src.mcp_server"],
    root=pathlib.Path("/somewhere/charlie"),
)
"""Stands in for an employee's own. Nothing here reaches the filesystem."""


def config(model: str = "gpt-5.6-luna", effort: str = "medium") -> Config:
    """A deployment, built rather than loaded, so nothing here depends on a
    `.env` that happens to be beside the test run."""
    return Config(
        model=ModelConfig(
            name=model,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            api="responses",
            reasoning=effort,
        ),
        shop=ShopConfig(base_url="", api_key="", timezone="UTC"),
        matomo=MatomoConfig(base_url="", token="", site_id="1"),
        loki=LokiConfig(base_url=""),
        queue=QueueConfig(url="", namespace=""),
        feed=FeedConfig(host="", port=22, user="", password="", directory=""),
        timeout_s=1.0,
    )


def session(**overrides: object) -> Session:
    """A session against a fake server, with only the fields a request reads."""
    fields: dict[str, object] = {
        "cwd": pathlib.Path("."),
        "env": {},
        "config": {},
        "provider": PROVIDER,
        "model": "gpt-5.6-luna",
        "system": SYSTEM_PROMPT,
    }
    fields.update(overrides)
    return Session(**fields)  # type: ignore[arg-type]


def _server(seen: list[dict], messages: list[dict] | None = None) -> httpx.AsyncClient:
    """A fake opencode that records what it was asked."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_1"})
        if request.method == "POST":
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"info": {"role": "assistant"}})
        return httpx.Response(200, json=messages or [])

    return httpx.AsyncClient(
        base_url="http://opencode.test", transport=httpx.MockTransport(handler)
    )


# ── the request shape ────────────────────────────────────────────────────────


async def test_the_model_is_nested_under_model_not_sent_flat():
    """The bug that cost the most. Sent flat as `providerID`/`modelID`, opencode
    ignores them WITHOUT COMPLAINT and runs its own default — here a local model
    that was not loaded. The run came back with one model request, no tokens and
    no tool calls, and read exactly like a model refusing to work."""
    seen: list[dict] = []
    async with _server(seen) as http:
        await converse(http, session(), "ticket")

    assert seen, "the message must be posted"
    body = seen[0]
    assert body["model"] == {"providerID": "archipel", "modelID": "gpt-5.6-luna"}
    assert "providerID" not in body, "flat keys are silently ignored by opencode"
    assert "modelID" not in body


async def test_the_ticket_and_brief_reach_the_session():
    seen: list[dict] = []
    async with _server(seen) as http:
        await converse(http, session(), "sales look off")

    body = seen[0]
    assert body["parts"] == [{"type": "text", "text": "sales look off"}]
    assert body["system"].startswith("You are an analyst at TimberWorks")


async def test_a_refusing_server_is_reported_rather_than_an_empty_session():
    """A 4xx that returned quietly would produce a record of zero tool calls,
    which is indistinguishable from a model that did nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_1"})
        return httpx.Response(400, json={"error": "Malformed JSON in request body"})

    async with httpx.AsyncClient(
        base_url="http://opencode.test", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await converse(http, session(), "ticket")


# ── the server this employee is started with ─────────────────────────────────


def test_the_provider_is_built_from_the_same_env_every_employee_reads():
    """One source of truth for "the same model": every employee configures from
    `AGENT_MODEL_*` in its own `.env`, and this translates rather than keeping a
    second setting that could drift.

    It is also why these employees genuinely honour a campaign's `--base-url`
    where the desk-driven ones cannot: the endpoint is theirs to pass on."""
    cfg = config()
    provider = server_config(cfg, TOOLS)["provider"][PROVIDER]

    assert provider["options"]["baseURL"] == cfg.model.base_url
    assert provider["options"]["apiKey"] == cfg.model.api_key
    assert cfg.model.name in provider["models"]


def test_the_openai_sdk_is_used_and_not_the_compatible_shim():
    """`@ai-sdk/openai-compatible` sends `reasoningSummary`, which the real API
    rejects with `Unknown parameter`. opencode records that on the assistant
    message, so the run reported one request, zero tokens and zero tool calls —
    a harness failure wearing a model failure's clothes."""
    provider = server_config(config(), TOOLS)["provider"][PROVIDER]

    assert provider["npm"] == "@ai-sdk/openai"


def test_it_may_not_run_commands_edit_files_or_reach_the_web():
    """It investigates a company through the tools it was given. opencode ships
    a shell, an editor and a fetcher enabled by default, and each of them is a
    way out of the toolset being measured."""
    permission = server_config(config(), TOOLS)["permission"]

    assert permission == {"bash": "deny", "edit": "deny", "webfetch": "deny"}


def test_the_tools_are_declared_so_opencode_can_launch_them():
    mcp = server_config(config(), TOOLS)["mcp"][TOOLS.namespace]

    assert mcp["enabled"] is True
    assert mcp["command"] == ["uv", "run", "python", "-m", "src.mcp_server"]


def test_the_reasoning_depth_is_pinned_and_shared():
    """The variable nobody had set. pydantic-ai sent nothing and let the API
    decide; opencode sent parameters of its own — caught by an
    `Unknown parameter: reasoningSummary` rejection. Two harnesses thinking at
    different depths cannot be compared, and the gap would have been read as a
    property of the harness."""
    cfg = config(effort="high")
    models = server_config(cfg, TOOLS)["provider"][PROVIDER]["models"]

    assert models[cfg.model.name]["options"]["reasoningEffort"] == "high"


def test_the_brief_is_the_shared_one_plus_only_the_output_shape():
    """Composed by the harness rather than by each employee, because enforcing
    the answer is the harness's job. Two employees appending their own sentence
    would be two employees a campaign could no longer compare."""
    assert SYSTEM_PROMPT == BRIEF + JSON_VERDICT


def test_the_tool_server_runs_in_the_employee_s_project_not_the_scratch_dir():
    """`uv run python -m src.mcp_server` resolves both halves from the project:
    the virtualenv from its `pyproject.toml`, the module from `src` beside it.
    Started in the run's workspace it would find neither."""
    harness = opencode_mcp.build(config(), TOOLS)

    assert isinstance(harness, McpHarness)
    assert harness._server.root == pathlib.Path("/somewhere/charlie")


# ── what the record is built from ────────────────────────────────────────────


def message(*parts: dict) -> dict:
    return {"info": {"role": "assistant"}, "parts": list(parts)}


def tool(name: str, **state: object) -> dict:
    return {"type": "tool", "tool": name, "state": state}


def test_a_call_and_its_result_are_one_record():
    """The pairing comes from walking the steps, in `record.from_steps`, rather
    than from a converter of this driver's own. It was written three times in
    this repository and got wrong once."""
    calls = from_steps(
        steps(
            [
                message(
                    tool(
                        "archipel_shop_get",
                        status="completed",
                        input={"resource": "orders"},
                        output='{"rows": []}',
                        time={"start": 100, "end": 250},
                    )
                )
            ]
        )
    )

    assert len(calls) == 1
    assert calls[0].tool == "archipel_shop_get"
    assert calls[0].input == {"resource": "orders"}
    assert calls[0].output == '{"rows": []}'
    assert calls[0].duration_ms == 150
    assert calls[0].status == "completed"


def test_a_tool_that_declared_an_error_is_not_recorded_as_success():
    """These tools never raise; they return `{"error": ...}`, so opencode marks
    them `completed` and the harness's own status would count a refused read as
    a good one. The grader reads this field, so it is a measured column."""
    calls = from_steps(
        steps([message(tool("archipel_shop_get", status="completed",
                            output='{"error": "403 from the Webservice"}'))])
    )

    assert calls[0].status == "error"


def test_the_word_error_in_ordinary_text_is_not_a_failure():
    """What separates a contract check from a regex hunting the word through
    arbitrary text, which will lie the first time a tool legitimately returns a
    field of that name."""
    calls = from_steps(
        steps([message(tool("archipel_logs_query", status="completed",
                            output="matched: error rate 0"))])
    )

    assert calls[0].status == "completed"


def test_a_refused_call_reads_its_error_and_not_its_missing_output():
    """A refused call has no `output` key AT ALL. Reading only `output` turned
    six blocked commands into six empty successes in one real run: the judge saw
    empty results and read them as calls that simply returned nothing, while the
    answer rested on evidence the loop had never been allowed to gather."""
    call, returned = steps(
        [message(tool("archipel_feed_read_file", status="error",
                      input={"name": "carriers.csv"}, error="permission denied"))]
    )

    assert call.kind is Kind.TOOL
    assert returned.kind is Kind.ERROR
    assert returned.text == "permission denied"


def test_an_unfinished_call_has_no_duration_rather_than_a_zero():
    """A run killed mid-call is exactly when the duration matters, and recording
    it as instant would say the opposite of what happened."""
    calls = from_steps(
        steps([message(tool("archipel_logs_query", status="running",
                            time={"start": 100, "end": None}))])
    )

    assert calls[0].duration_ms is None


def test_a_named_call_keeps_its_arguments_rather_than_a_command_line():
    """Every tool here is a named call with structured arguments. Flattened into
    a command string, `input` reaches the record as `{"command": "..."}` — the
    one thing these calls never had."""
    call, _returned = steps(
        [message(tool("archipel_data_filter", status="completed",
                      input={"dataset": "orders", "where": ["iso_code=CA"]}))]
    )

    assert call.kind is Kind.TOOL
    assert call.command == ""
    assert call.args == {"dataset": "orders", "where": ["iso_code=CA"]}


def test_a_call_still_running_is_not_recorded_as_one_that_returned():
    """A conversation read back mid-turn carries parts marked `running`.

    Anything-that-is-not-`error` used to become a plain result, so a call still
    executing was recorded as one that had returned — empty output, clean
    status. The record then said the loop had read something it was in fact
    still waiting for.
    """
    produced = steps(
        [message(tool("archipel_logs_query", status="running",
                      input={"service": "camel"}))]
    )

    assert len(produced) == 1, "a running call has no result step"
    assert produced[0].kind is Kind.TOOL

    from core.record import from_steps

    (recorded,) = from_steps(list(produced))
    assert recorded.status == "pending"
