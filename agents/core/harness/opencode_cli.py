"""The opencode loop, driven with a **desk**.

opencode is handed a working directory laid out as a desk — an `AGENTS.md`, a
directory of skills, a shell that may run commands — and finds the company by
using it. That is the whole of what this file decides; the mechanics of driving
the server live in `opencode_api`, which the MCP-equipped driver shares.

Two details here are load-bearing, both learned the expensive way:

The model is declared in the server's configuration, under a provider opencode
already knows. Without that block the turn fails with
`ProviderModelNotFoundError`, which arrives as an empty 2xx and reads like a
model that would not answer.

The answer shape has to be asked for in words, because there is no
`--output-schema` here. It is then validated on the way out, so a loop that
ignored the instruction fails as a bad answer rather than as a bad key.

The module is `opencode_cli` while the harness is `opencode`: the name a record
carries is the vendor's, and the file is named so that importing it can never
shadow the tool it drives.
"""

import json
import pathlib
from collections.abc import Callable
from typing import Any

from core.config import Config
from core.contract import ANSWER_SCHEMA
from core.harness import opencode_api
from core.harness.base import Harness, Outcome, Step
from core.harness.desk import Desk, brief, child_env, prepare
from core.harness.policy import OPENCODE_PERMISSIONS

PROVIDER = "openai"
"""Whose catalogue the model name is looked up in.

Not read from `Config`, which describes an OpenAI-shaped *endpoint* rather than
an opencode provider id. Sending one where the other is expected fails as
`ProviderModelNotFoundError`, which arrives as an empty 2xx and reads like a
model that would not answer."""


def build(config: Config, desk: Desk) -> Harness:
    """The opencode loop, as one employee's configuration describes it.

    The desk is passed rather than found. Which brief and which credentials a
    loop runs with is the employee's, and this driver is shared by all of them.
    """
    return OpencodeHarness(
        desk=desk,
        # Computed once, here: the only place holding both the desk (which names
        # what the role may reach) and the configuration (which holds the
        # values). The harness carries the result, not the configuration.
        env=child_env(desk, config),
        model=config.model.name,
        effort=config.model.reasoning,
        timeout_s=config.timeout_s,
    )


def system(desk: Desk) -> str:
    """The same brief codex reads from `AGENTS.md`, passed explicitly.

    codex discovers `AGENTS.md` in its working directory; opencode is handed the
    identical text here rather than left to find it. Two harnesses reading
    different briefs would make every comparison between them a comparison of
    briefs.

    The schema sentence is the one mechanical difference: opencode has no
    `--output-schema`, so the shape is asked for in words and checked on the way
    out. It says how to answer, never what to look for.
    """
    return (
        brief(desk)
        + "\n\nReply with one JSON object and nothing else, matching this schema: "
        + json.dumps(ANSWER_SCHEMA)
    )


class OpencodeHarness:
    """One `opencode serve` per investigation, over a desk.

    A plain class rather than a frozen dataclass so its fields can keep the
    underscored names the rest of the package reads them by.
    """

    name = opencode_api.HARNESS

    def __init__(
        self,
        desk: Desk,
        env: dict[str, str],
        model: str = "",
        effort: str = "",
        provider: str = PROVIDER,
        timeout_s: float = 300.0,
    ) -> None:
        self._desk = desk
        self._env = env
        self._model = model
        self._effort = effort
        self._provider = provider
        self._timeout = timeout_s

    async def investigate(
        self,
        ticket: str,
        workdir: pathlib.Path,
        on_step: Callable[[Step], None] | None = None,
    ) -> Outcome:
        # **The desk is laid out here, by the driver that has one.** It used to
        # be done by each agent's own service, one line before the loop was
        # called; when that service moved into the shared package the call had
        # nowhere to go — `run.investigate` knows nothing about desks, correctly
        # — and it was simply lost. Nothing failed loudly: the loop started in
        # an empty directory with no skills, no brief and no certificate, and
        # reported an investigation that had nothing to investigate with.
        prepare(self._desk, workdir)
        return await opencode_api.run(
            opencode_api.Session(
                cwd=workdir,
                # Built, not merged — the same environment codex gets. Merging
                # handed a `bash: allow` loop the employee's bus URL and
                # namespace, enough to write onto its own action stream; codex
                # was filtered after the fact by `shell_environment_policy`, this
                # side by nothing.
                #
                # A first attempt at this looked like it broke opencode. It had
                # not: the turn was failing for two unrelated reasons at once —
                # an undeclared model and a missing provider key — and the built
                # environment was blamed for both.
                env=self._env,
                config=server_config(self._provider, self._model, self._effort),
                provider=self._provider,
                model=self._model,
                system=system(self._desk),
                timeout_s=self._timeout,
            ),
            ticket,
            on_step,
        )


def server_config(
    provider: str = "", model: str = "", effort: str = ""
) -> dict[str, Any]:
    """What the server is started with.

    Handed in through `OPENCODE_CONFIG_CONTENT` rather than written to a file,
    so nothing about the role lands on disk beside the code.

    Reasoning effort rides here rather than on the message, because opencode
    settles model options per provider-model rather than per request. Left out
    entirely when unset, so the server keeps its own default instead of being
    pinned to a value nobody chose.
    """
    config: dict[str, Any] = {
        "$schema": opencode_api.SCHEMA,
        "permission": dict(OPENCODE_PERMISSIONS),
    }
    if provider and model:
        # The model is declared whether or not an effort is set, because this
        # block is what makes opencode *know* the model at all: without it the
        # turn fails with `ProviderModelNotFoundError`, the server answers 2xx
        # with an empty body, and the driver blamed the answer's shape.
        #
        # Gating the whole block on `effort` meant opencode worked in campaigns
        # (which pass one) and failed everywhere else — a defect that survived a
        # full day because the functional suite only ever ran codex.
        options = {"reasoningEffort": effort} if effort else {}
        config["provider"] = {provider: {"models": {model: {"options": options}}}}
    return config
