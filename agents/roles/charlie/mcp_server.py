"""Charlie's tools, exposed over MCP so opencode can call them.

This file is the entire seam between the two halves of the experiment. Below it,
Python that reads the company — the same systems Angel reaches, with Charlie's
own credentials. Above it, opencode's agent loop, which we do not write.

That is the point. Angel's harness is ours: our loop, our retry rules, our
context discipline. Charlie's is opencode's. Holding the *job* and the *grader*
fixed while swapping the harness is what makes the comparison mean anything.

Run as a stdio server, launched by opencode itself — see `opencode.json`. It
never listens on a port, so nothing but opencode can reach it.
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from core.config import Config, load
from roles.charlie import tools

server = MCPServer(
    name="archipel",
    instructions=(
        "Read-only access to the company: the shop's Webservice, its logs, and "
        "the ERP feed the integration consumes. Every call is a read."
    ),
)

_cfg: Config | None = None


def cfg() -> Config:
    """Credentials, loaded once per process.

    Charlie's own `.env`, never Angel's: separate credentials are what make the
    access boundary real rather than declarative, and the shop enforces it.
    """
    global _cfg
    if _cfg is None:
        _cfg = load()
    return _cfg


@server.tool(description="Every resource the shop exposes to this identity.")
def shop_resources() -> dict[str, Any]:
    return tools.shop_resources(cfg())


@server.tool(description="The fields of one shop resource, from its own schema.")
def shop_schema(resource: str) -> dict[str, Any]:
    return tools.shop_schema(cfg(), resource)


@server.tool(
    description=(
        "Read rows from a shop resource. `fields` selects columns, `filters` maps "
        "a field to a value. Shows at most 25 rows and says whether that was all "
        "of them: `complete` is true, false or unknown, and when it is not true "
        "`next_offset` says where to continue. Raise `limit` to have more counted."
    )
)
def shop_get(
    resource: str,
    fields: list[str] | None = None,
    filters: dict[str, str] | None = None,
    limit: int = tools.MAX_ROWS,
    offset: int = 0,
) -> dict[str, Any]:
    return tools.shop_get(cfg(), resource, fields, filters, limit, offset)


@server.tool(description="Which reports the web analytics has, from itself.")
def analytics_reports() -> dict[str, Any]:
    return tools.analytics_reports(cfg())


@server.tool(
    description=(
        "Call one web-analytics method with its own parameters. A refusal comes "
        "back as an error, not as an empty result."
    )
)
def analytics_get(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return tools.analytics_get(cfg(), method, params)


@server.tool(description="Which systems are sending logs.")
def logs_services() -> dict[str, Any]:
    return tools.logs_services(cfg())


@server.tool(
    description=(
        "Search one service's recent log for a regular expression. Reports how "
        "many lines matched and shows at most 40, each clipped."
    )
)
def logs_query(service: str, pattern: str, minutes: int = 30) -> dict[str, Any]:
    return tools.logs_query(cfg(), service, pattern, minutes)


@server.tool(description="The files the ERP has dropped for the integration.")
def feed_list_files() -> dict[str, Any]:
    return tools.feed_list_files(cfg())


@server.tool(description="Read one ERP feed file.")
def feed_read_file(name: str) -> dict[str, Any]:
    return tools.feed_read_file(cfg(), name)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
