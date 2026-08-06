"""What is Charlie's alone, now that the loop is not.

The driver, the record and the envelope moved to `core` and are checked
there. Two things did not: the tool server this employee declares, and the fact
that starting it never puts a credential on disk beside the code.
"""

import pathlib
import sys

from core.harness.opencode_mcp import McpHarness
from roles.charlie.identity import AGENT, IDENTITY, MCP

AGENTS = pathlib.Path(__file__).resolve().parents[2]
"""The one project root — what the server is launched from."""

HERE = AGENTS / "roles" / "charlie"
"""This employee's own directory, which is no longer the project root."""


def test_the_declared_tools_are_this_employee_s_own():
    """Named as a module of this employee, so the server that starts is the one
    holding Charlie's credentials. Pointed anywhere else it would be another
    employee investigating under this name.

    `sys.executable` rather than `uv run`: there is one environment now, so the
    interpreter already running is the one the server needs and there is no
    project left for uv to resolve."""
    assert MCP.command == [sys.executable, "-m", "roles.charlie.mcp_server"]
    assert MCP.root == AGENTS


def test_the_namespace_matches_the_server_s_own_name():
    """opencode prefixes the tools with it — `archipel_shop_get` — and the
    grader strips that prefix to compare a call against another employee's. A
    second name would be invisible to it."""
    from roles.charlie import mcp_server

    assert MCP.namespace == mcp_server.server.name


def test_the_identity_serves_under_the_employee_s_name():
    assert IDENTITY.name == AGENT == "charlie"
    assert isinstance(IDENTITY.build(_config()), McpHarness)


def test_no_credential_is_checked_in_beside_the_code():
    """The provider is handed to opencode through `OPENCODE_CONFIG_CONTENT`.
    `opencode.json` exists for a developer running `opencode` in this directory
    by hand, and must stay the part with no secret in it."""
    checked_in = HERE / "opencode.json"
    if not checked_in.is_file():
        return
    written = checked_in.read_text()

    assert "apiKey" not in written
    assert "provider" not in written


def _config():
    from core.config import (
        Config,
        FeedConfig,
        LokiConfig,
        MatomoConfig,
        ModelConfig,
        QueueConfig,
        ShopConfig,
    )

    return Config(
        model=ModelConfig(name="m", base_url="", api_key=""),
        shop=ShopConfig(base_url="", api_key="", timezone="UTC"),
        matomo=MatomoConfig(base_url="", token="", site_id="1"),
        loki=LokiConfig(base_url=""),
        queue=QueueConfig(url="", namespace=""),
        feed=FeedConfig(host="", port=22, user="", password="", directory=""),
    )
