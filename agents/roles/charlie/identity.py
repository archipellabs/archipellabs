"""Who Charlie is: a thin toolset over MCP, and opencode's loop.

Everything else — the ticket, the events, the record, the envelope, the bus mount
— is `core`. What is left here is the part that makes this employee a
distinct one: the tools it can reach, and the fact that opencode rather than
pydantic-ai decides when to call them.

    angel   = our loop  + rich tools
    charlie = opencode  + thin tools     ← this one
    dana    = opencode  + Angel's tools  ← the control that separates the two

**No `routable` guard here**, unlike the desk-driven employees. Those reach a
model through a CLI's own provider configuration and quietly ignore a `--base-url`
passed from outside, so a campaign labelling a row with an endpoint they never
called has to be refused. Charlie's provider is *built* from `cfg.model.base_url`
and the key beside it — see `opencode_mcp.PROVIDER` — so the endpoint a campaign
names is the endpoint the run uses, and every model is genuinely comparable.
"""

import pathlib
import sys

from core import Identity
from core.harness import opencode_mcp
from core.harness.opencode_mcp import McpServer

AGENT = "charlie"

MCP = McpServer(
    # Plain `python -m`, not `uv run`. There is one environment now, so there is
    # no project for uv to resolve — and the interpreter running this process is
    # already the one the server needs.
    command=[sys.executable, "-m", "roles.charlie.mcp_server"],
    root=pathlib.Path(__file__).resolve().parents[2],
)
"""Charlie's tools, as opencode is told to start them.

A stdio process launched by opencode itself, so it never listens on a port and
nothing but opencode can reach it. `root` is this project rather than the run's
scratch directory: `uv run` resolves the virtualenv from the `pyproject.toml`
here, and `python -m src.mcp_server` the module from `src` beside it.
"""

IDENTITY = Identity(AGENT, lambda cfg: opencode_mcp.build(cfg, MCP))
