"""The opencode loop, driven with an **MCP server** instead of a desk.

The other opencode driver hands the loop a directory of skills and a shell, and
lets it work out how to reach the company. This one hands it typed tools over MCP
and takes the shell away: `bash`, `edit` and `webfetch` are denied, so every read
of the company goes through a function somebody wrote, and what the employee can
see is a list rather than an argument about what a shell could reach.

That is the whole difference between the two files. Starting the server, posting
the ticket, reading the conversation back, counting what it spent and finding the
verdict in the prose are `opencode_api`'s, and shared, because they were the same
code twice and had already drifted once.

Two things here are this driver's alone:

**The provider is built from the employee's own configuration.** `openai` is not
configured in opencode on these machines, and relying on whatever a developer
happened to authenticate would make the model under test depend on the machine —
the one thing a campaign may not do. So `AGENT_MODEL_BASE_URL` and the key become
a named provider, which is also why these employees genuinely honour a
campaign's `--base-url` where the desk-driven ones cannot.

**A tool that answered "I cannot do that" did not succeed.** The tools never
raise; they return `{"error": ...}`, so opencode marks the call `completed` and
the neutral record would count a refused read as a good one. That contract is the
tools', not opencode's, so it is read here rather than in the shared translator.
"""

import dataclasses
import json
import os
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.brief import BRIEF, JSON_VERDICT
from core.config import Config
from core.harness import opencode_api
from core.harness.base import Harness, Kind, Outcome, Step
from core.harness.policy import OPENCODE_MCP_PERMISSIONS

SYSTEM_PROMPT = BRIEF + JSON_VERDICT
"""The shared brief, plus the only difference the harness forces.

opencode returns prose where a typed loop returns an object, so the answer's
SHAPE has to be asked for. It says how to reply, never what to look for.

Composed **here** rather than in each employee, because enforcing the answer is
the harness's job: pydantic-ai makes the verdict a tool the model must satisfy
and opencode cannot, so the sentence that stands in for that belongs beside the
loop that needs it. Two employees that each appended their own would be two
employees a campaign could no longer compare, and the wording is the easiest
thing in the system to change by accident."""

PROVIDER = "archipel"
"""The provider opencode is given, built from the employee's own config.

Named rather than borrowed. Every employee configures identically —
`AGENT_MODEL_NAME`, `AGENT_MODEL_BASE_URL` and the API key, out of its own
`.env`; the pydantic-ai lineage hands those to its client and this translates
them into an opencode provider. One source of truth, so "the same model" means
the same model."""

SDK = "@ai-sdk/openai"
"""Not `@ai-sdk/openai-compatible`.

The compatible shim sends `reasoningSummary`, which the real API rejects with
`Unknown parameter` — and opencode records that as an assistant-level error, so
the run came back with one model request, zero tokens and zero tool calls and
read exactly like a model that had refused to work.

The cost is that a local LM Studio endpoint is no longer certain to accept every
parameter this provider sends. Worth knowing before pointing one of these
employees at gemma; the hosted case is the one the comparison needs."""


@dataclass(frozen=True)
class McpServer:
    """One employee's tools: how to launch them, and where from.

    The MCP analogue of a `Desk`, and it carries the same kind of thing — what
    the employee is given, as data an experiment can vary — rather than
    credentials, which are read from the environment by the server process
    itself.
    """

    command: list[str]
    """How opencode starts the tool server, as a local stdio process. It never
    listens on a port, so nothing but opencode can reach it."""
    root: pathlib.Path
    """Where that command runs, which is the employee's own project.

    Not the run's scratch workspace, unlike the desk driver: the command is
    `uv run python -m src.mcp_server`, and both halves of that resolve from the
    project — the virtualenv from its `pyproject.toml`, the module from `src`
    beside it. opencode gives a local MCP server its own working directory, so
    this is the server's cwd as well as the session's."""
    namespace: str = "archipel"
    """What opencode prefixes the tools with — `archipel_shop_get`.

    Must match the MCP server's own declared name. A second name would be
    invisible to the grader, which strips this one to compare a call against
    another employee's."""


def build(config: Config, server: McpServer) -> Harness:
    """The opencode loop, as one employee's configuration describes it.

    The tools are passed rather than found, exactly as the desk is on the other
    driver: which tools an employee holds is the employee's, and this driver is
    shared by all of them.
    """
    return McpHarness(server=server, config=config)


def server_config(config: Config, server: McpServer) -> dict[str, Any]:
    """What the server is started with.

    Handed in through `OPENCODE_CONFIG_CONTENT` rather than written to a file, so
    the provider key never lands on disk beside the code.
    """
    return {
        "$schema": opencode_api.SCHEMA,
        "mcp": {
            server.namespace: {
                "type": "local",
                "enabled": True,
                "command": list(server.command),
            }
        },
        "permission": dict(OPENCODE_MCP_PERMISSIONS),
        "provider": {
            PROVIDER: {
                "npm": SDK,
                "name": PROVIDER,
                "options": {
                    "baseURL": config.model.base_url,
                    "apiKey": config.model.api_key,
                },
                "models": {
                    config.model.name: {
                        "name": config.model.name,
                        # The same depth every employee is pinned to, from the
                        # same variable. opencode otherwise picks its own, which
                        # is how two harnesses came to think differently without
                        # anyone choosing that.
                        "options": {"reasoningEffort": config.model.reasoning},
                    }
                },
            }
        },
    }


class McpHarness:
    """One `opencode serve` per investigation, over a set of MCP tools."""

    name = opencode_api.HARNESS

    def __init__(self, server: McpServer, config: Config) -> None:
        self._server = server
        self._config = config

    async def investigate(
        self,
        ticket: str,
        workdir: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> Outcome:
        """Run once, in the employee's project rather than in `workdir`.

        The directory is accepted and not used, which is worth saying out loud.
        A desk is *laid out* in the scratch directory it is given; a tool server
        cannot be, because `uv run python -m src.mcp_server` resolves against the
        project it belongs to. The tools keep their own per-run scratch space —
        see each employee's `workspace` tool — so nothing is shared between runs
        by this.
        """
        return await opencode_api.run(
            opencode_api.Session(
                cwd=self._server.root,
                env=child_env(),
                config=server_config(self._config, self._server),
                provider=PROVIDER,
                model=self._config.model.name,
                system=SYSTEM_PROMPT,
                timeout_s=self._config.timeout_s,
                read_steps=steps,
            ),
            ticket,
            on_step,
        )


def child_env() -> dict[str, str]:
    """The environment the server process is given: this one, whole.

    The desk driver builds an allow-list instead, and the asymmetry is deliberate
    rather than an oversight. There it is a boundary that has to hold against the
    model itself: `bash` is allowed, so a command the model writes could read the
    employee's bus URL and namespace and write onto its own action stream. Here
    `bash`, `edit` and `webfetch` are denied and the model has no way to read an
    environment variable at all — what needs this environment is opencode itself
    and the tool server it launches, both of which are ours.

    And they need most of it. `uv run` resolves an interpreter from `PATH`,
    `HOME` and its own cache; the tool server reads the employee's `.env`
    relative to `AGENT_ENV_FILE`, and its scratch directories from
    `AGENT_WORKSPACE_DIR`, `AGENT_LOG_DIR` and `AGENT_DATA_DIR`. An allow-list
    here would be a list of everything a campaign sets, maintained in a second
    place, failing silently one variable at a time.

    A function rather than `os.environ` inline, so the reason is somewhere a
    reader will find it and the choice can be seen being made.
    """
    return dict(os.environ)


def steps(messages: Any) -> list[Step]:
    """The conversation as steps, with the tools' own refusals honoured."""
    return [_declared(step) for step in opencode_api.steps(messages)]


def _declared(step: Step) -> Step:
    """A tool that answered "I cannot do that" did not succeed.

    opencode's status only says the call *ran*: these tools never raise, they
    return `{"error": ...}`, so a Webservice 403 and a good read are both
    `completed` and the record counts a refusal as evidence. The grader reads
    that field — a call recorded `error` is a rejection in its report — so the
    difference is a measured column and not a nicety.

    This parses the output and looks for a key those tools define. It is a check
    against a contract, not a regular expression hunting the word "error" through
    arbitrary text, which will lie the first time a tool legitimately returns a
    field of that name — and it is scoped to this driver for the same reason: on
    the desk side the same output is a shell command's, and nobody promised
    anything about its shape.
    """
    if step.kind is not Kind.OUTPUT:
        return step
    try:
        payload = json.loads(step.text)
    except (json.JSONDecodeError, ValueError):
        return step
    if isinstance(payload, dict) and "error" in payload:
        return dataclasses.replace(step, kind=Kind.ERROR)
    return step
