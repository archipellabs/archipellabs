"""What is Dana's alone, now that the loop is not.

The driver, the record and the envelope moved to `core` and are checked
there. What stays here is the tool server this employee declares, which is the
half of Dana that must not drift — the other half, that those tools are Angel's
verbatim, is `test_parity_unit`.
"""

import pathlib
import sys

from core.harness.opencode_mcp import McpHarness
from roles.dana.identity import AGENT, IDENTITY, MCP

AGENTS = pathlib.Path(__file__).resolve().parents[2]
"""The one project root — what the server is launched from."""


def test_the_declared_tools_are_this_employee_s_own():
    """Named as a module of this employee, so the server that starts is the one
    holding Dana's credentials. Pointed anywhere else it would be another
    employee investigating under this name.

    `sys.executable` rather than `uv run`: there is one environment now, so the
    interpreter already running is the one the server needs and there is no
    project left for uv to resolve."""
    assert MCP.command == [sys.executable, "-m", "roles.dana.mcp_server"]
    assert MCP.root == AGENTS


def test_the_namespace_matches_the_server_s_own_name():
    """opencode prefixes the tools with it — `archipel_shop_get` — and the
    grader strips that prefix to compare a call against Angel's. A second name
    would be invisible to it."""
    from roles.dana import mcp_server

    assert MCP.namespace == mcp_server.server.name


def test_the_identity_serves_under_the_employee_s_name():
    assert IDENTITY.name == AGENT == "dana"
    assert isinstance(IDENTITY.build(_config()), McpHarness)


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
