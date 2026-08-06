"""Who Dana is: Angel's tools over MCP, and opencode's loop.

Everything else — the ticket, the events, the record, the envelope, the bus mount
— is `core`. What is left here is the part that makes this employee a
distinct one, and Dana's whole reason for existing is that it is *one* part:

    angel   = our loop  + these tools
    dana    = opencode  + these tools    ← the only difference is the loop
    charlie = opencode  + thinner tools

The `tools/` package beside this file is Angel's, copied verbatim, and a test
asserts it stays that way. Reimplemented, every fix Angel earned — the
completeness envelope, the client-side sort, the translated Webservice refusals —
would have to be earned again, and the two would diverge exactly where it matters.

**No `routable` guard here**, unlike the desk-driven employees: Dana's provider
is built from `cfg.model.base_url` and the key beside it, so the endpoint a
campaign names is the endpoint the run uses.
"""

import pathlib
import sys

from core import Identity
from core.harness import opencode_mcp
from core.harness.opencode_mcp import McpServer

AGENT = "dana"

MCP = McpServer(
    # Plain `python -m`, not `uv run`. There is one environment now, so there is
    # no project for uv to resolve — and the interpreter running this process is
    # already the one the server needs.
    command=[sys.executable, "-m", "roles.dana.mcp_server"],
    root=pathlib.Path(__file__).resolve().parents[2],
)
"""Dana's tools, as opencode is told to start them.

A stdio process launched by opencode itself, so it never listens on a port and
nothing but opencode can reach it. `root` is this project rather than the run's
scratch directory: `uv run` resolves the virtualenv from the `pyproject.toml`
here, and `python -m src.mcp_server` the module from `src` beside it.
"""

IDENTITY = Identity(AGENT, lambda cfg: opencode_mcp.build(cfg, MCP))
