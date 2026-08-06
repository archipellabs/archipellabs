"""Angel's tools, over MCP, for opencode to drive.

Dana is the control that the three-harness campaign asked for. Charlie showed
opencode solving the incident three times out of three on a ninth of the tokens
— but Charlie's tools are thinner than Angel's, so that result measured
*orchestration plus tools* and could not say which half mattered.

Dana holds the tools constant instead. **The `tools/` package here is Angel's,
copied verbatim**: the completeness envelope, the client-side sort, the
translated Webservice refusals, the relational primitives, the per-run
workspace. Every one of those was added because a graded run went wrong without
it. What changes against Angel is only the loop.

    angel   = our loop      + these tools
    dana    = opencode      + these tools      ← the difference is the loop
    charlie = opencode      + thin tools

The clients are opened once for the process and shared by every call. An MCP
server is one process serving one investigation, so their lifetime is the run's,
and reopening a connection per tool call would put a TLS handshake in front of
each read.
"""

import asyncio
import atexit
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from core.config import Config, load
from roles.dana.tools import analytics, data, feed, logs, shop

server = MCPServer(
    name="archipel",
    instructions=(
        "Read-only access to the company: the shop's Webservice, Matomo, the "
        "logs, and the ERP feed the integration consumes. Every call is a read."
    ),
)

_cfg: Config | None = None
_clients: dict[str, httpx.AsyncClient] = {}


def cfg() -> Config:
    """Credentials, loaded once. Dana's own `.env`, never another employee's."""
    global _cfg
    if _cfg is None:
        _cfg = load()
    return _cfg


def _client(kind: str) -> httpx.AsyncClient:
    if kind not in _clients:
        builders = {
            "shop": lambda: shop.client(cfg().shop),
            "matomo": lambda: analytics.client(cfg().matomo),
            "loki": lambda: logs.client(cfg().loki),
        }
        _clients[kind] = builders[kind]()
    return _clients[kind]


@atexit.register
def _close() -> None:
    for client in _clients.values():
        with __import__("contextlib").suppress(Exception):
            asyncio.get_event_loop().run_until_complete(client.aclose())


# ── the shop ─────────────────────────────────────────────────────────────────


@server.tool(description="Every resource the shop exposes to this identity.")
async def shop_resources() -> list[dict[str, Any]]:
    return await shop.resources(_client("shop"))


@server.tool(description="The fields of one shop resource, from its own schema.")
async def shop_schema(resource: str) -> dict[str, Any]:
    return await shop.schema(_client("shop"), resource)


@server.tool(
    description=(
        "Read rows from a shop resource. `fields` selects columns, `filters` maps "
        "a field to a value, `sort` takes FIELD_ASC or FIELD_DESC. `into` saves "
        "the full result as a dataset for the data_* tools. Every answer declares "
        "how much of the truth it gave."
    )
)
async def shop_get(
    resource: str,
    fields: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    sort: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
    into: str | None = None,
) -> dict[str, Any]:
    params = shop.query_params(
        fields=fields, filters=filters, sort=sort, limit=limit, offset=offset
    )
    return await shop.get(_client("shop"), resource, params, into=into)


# ── analytics ────────────────────────────────────────────────────────────────


@server.tool(description="Which Matomo reports exist, from Matomo itself.")
async def analytics_reports() -> list[dict[str, Any]] | dict[str, Any]:
    # Matomo answers a refusal with HTTP 200 and `{"result": "error"}`, so this
    # returns a dict on failure and a list on success. Flattening the two would
    # hand back an empty list for "your token is wrong".
    return await analytics.reports(_client("matomo"), cfg().matomo)


@server.tool(description="Call one Matomo API method with its own parameters.")
async def analytics_get(
    method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    return await analytics.get(_client("matomo"), cfg().matomo, method, params)


# ── logs ─────────────────────────────────────────────────────────────────────


@server.tool(description="Which systems are sending logs.")
async def logs_services() -> list[str]:
    return await logs.services_logging(_client("loki"))


@server.tool(
    description=(
        "Every service's recent activity and what is NEW against the window "
        "before it. Answers 'what changed', which is the question an incident "
        "asks."
    )
)
async def logs_overview(minutes: int = 10) -> dict[str, Any]:
    return await logs.overview(_client("loki"), minutes)


@server.tool(description="Download a service's log window to a file, then search it.")
async def logs_query(
    service: str, pattern: str, minutes: int = 30, max_matches: int = 12
) -> dict[str, Any]:
    return await logs.query(
        _client("loki"), service, minutes, pattern, max_matches=max_matches
    )


@server.tool(
    description=(
        "Download a service's log window to a file without searching it. Returns "
        "facts about the file, never its contents."
    )
)
async def logs_fetch(service: str, minutes: int = 60) -> dict[str, Any]:
    return await logs.fetch(_client("loki"), service, minutes)


@server.tool(description="Read one long line from an offset, in bounded pieces.")
def logs_read(
    file: str, line_no: int, char_offset: int = 0, max_chars: int = 300
) -> dict[str, Any]:
    return logs.read_line(file, line_no, char_offset, max_chars)


@server.tool(description="Search a log file already downloaded.")
def logs_grep(
    file: str, pattern: str, ignore_case: bool = True, max_matches: int = 40
) -> dict[str, Any]:
    return logs.grep(file, pattern, ignore_case=ignore_case, max_matches=max_matches)


@server.tool(description="Read a window of lines around a known line number.")
def logs_slice(file: str, start: int = 1, count: int = 20) -> dict[str, Any]:
    return logs.slice_(file, start, count)


@server.tool(description="The log files downloaded so far in this investigation.")
def logs_files() -> list[dict[str, Any]]:
    return logs.files()


@server.tool(description="The most frequent line shapes in a downloaded log.")
def logs_patterns(file: str, max_patterns: int = 20) -> dict[str, Any]:
    return logs.patterns(file, max_patterns)


# ── datasets ─────────────────────────────────────────────────────────────────


@server.tool(description="The datasets saved so far, with row counts and fields.")
def data_datasets() -> list[dict[str, Any]]:
    return data.datasets()


@server.tool(
    description=(
        "Match two datasets on a key. `how` is inner, left, or anti — anti keeps "
        "only rows with nothing on the other side."
    )
)
def data_join(
    left: str, right: str, left_key: str, right_key: str, into: str, how: str = "inner"
) -> dict[str, Any]:
    return data.join(left, right, left_key, right_key, into, how)


@server.tool(
    description=(
        "Keep the rows matching every condition. Conditions look like "
        "`iso_code=CA`, `id_carrier!=0`, `total>100`, `date_add~2026-07-31`."
    )
)
def data_filter(dataset: str, where: list[str], into: str) -> dict[str, Any]:
    return data.filter_(dataset, where, into)


@server.tool(description="Read some actual rows of a dataset.")
def data_sample(
    dataset: str, fields: list[str] | None = None, limit: int = 10, offset: int = 0
) -> dict[str, Any]:
    return data.sample(dataset, fields, limit, offset)


@server.tool(
    description=(
        "Group a dataset and measure each group: count, sum:field, avg:field, "
        "min:field, max:field."
    )
)
def data_aggregate(
    dataset: str, group_by: list[str], measures: list[str] | None = None
) -> dict[str, Any]:
    return data.aggregate(dataset, group_by, measures)


@server.tool(description="The same aggregate over two datasets, with the delta.")
def data_compare(
    left: str, right: str, keys: list[str], measures: list[str] | None = None
) -> dict[str, Any]:
    return data.compare(left, right, keys, measures)


# ── the ERP feed ─────────────────────────────────────────────────────────────


@server.tool(description="The files the ERP has dropped for the integration.")
def feed_list_files() -> list[str]:
    return feed.list_files(cfg().feed)


@server.tool(description="Read one ERP feed file, from an offset if it is large.")
def feed_read_file(name: str, offset: int = 0) -> dict[str, Any]:
    return feed.read_file(cfg().feed, name, offset=offset)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
