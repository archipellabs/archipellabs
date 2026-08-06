"""Blair: an evidence-first incident analyst with a compact generic toolset.

Angel's neighbour and its control on the *tools* axis: the same loop, the same
brief and the same credentials, reached through a smaller and more generic
instrument — search a catalogue, query a source, put the rows in a table, join
and group them. Angel's toolset is wider and more specific. Which of the two an
investigation does better with is the question, and it is only a question while
everything else is held identical.

Everything else is: building the model, driving the loop, counting what it spent
and writing down what it did are `core.harness.pydantic_ai`, shared with
Angel. What is left here is the `Toolbox` — a type, its clients, and these
registrations.
"""

import contextlib
import pathlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic_ai import Agent, RunContext

from core.config import Config
from core.contract import Answer, Refusal
from core.harness.pydantic_ai import Toolbox, run_of
from roles.blair.tools import analytics, feed, logs, shop, tables, workspace


@dataclass
class Deps:
    """Live clients and credentials. Never visible to the model."""

    cfg: Config
    shop_http: httpx.AsyncClient
    analytics_http: httpx.AsyncClient
    logs_http: httpx.AsyncClient


@contextlib.asynccontextmanager
async def deps(cfg: Config, workdir: pathlib.Path) -> AsyncIterator[Deps]:
    """This run's clients, and this run's scratch, for exactly this run.

    Both in one context manager, because both are the investigation's and
    neither outlives it. The scratch used to be bound in a `try/finally` one
    layer up and the clients in an `async with` one layer down, which is two
    places to forget.

    Tables and downloaded logs are per run for the same reason as Angel's: names
    written by a previous run are hypotheses in disguise, and a process serving
    many tickets would hand each one the last one's conclusions.
    """
    token = workspace.use(run_of(workdir))
    try:
        async with (
            shop.client(cfg.shop) as shop_http,
            analytics.client(cfg.matomo) as analytics_http,
            logs.client(cfg.loki) as logs_http,
        ):
            yield Deps(cfg, shop_http, analytics_http, logs_http)
    finally:
        workspace.release(token)


def register(agent: Agent[Deps, Answer | Refusal]) -> None:
    """Every tool this identity holds, attached to one run's agent."""

    @agent.tool_plain
    def thought(thought: str = "") -> str:
        """Record a reasoning step before choosing the next piece of evidence."""
        return "noted"

    @agent.tool
    async def shop_catalog(
        ctx: RunContext[Deps], search: str = "", offset: int = 0
    ) -> dict[str, Any]:
        """Search shop API resources reachable with this read-only identity."""
        return await shop.catalog(ctx.deps.shop_http, search, offset)

    @agent.tool
    async def shop_describe(
        ctx: RunContext[Deps], resource: str
    ) -> dict[str, Any]:
        """List the fields of one shop resource before querying it."""
        return await shop.describe(ctx.deps.shop_http, resource)

    @agent.tool
    async def shop_query(
        ctx: RunContext[Deps],
        resource: str,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        sort: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        save_as: str | None = None,
    ) -> dict[str, Any]:
        """Read a shop resource with typed selection, filtering and paging.

        Sort terms use FIELD_ASC or FIELD_DESC. Date ranges use
        filters={"date_add":"[start,end]"}. With save_as, rows stay in a local
        table and only a small preview is returned.
        """
        return await shop.query(
            ctx.deps.shop_http,
            resource,
            fields=fields,
            filters=filters,
            sort=sort,
            limit=limit,
            offset=offset,
            save_as=save_as,
        )

    @agent.tool
    async def analytics_catalog(
        ctx: RunContext[Deps], search: str = "", offset: int = 0
    ) -> dict[str, Any]:
        """Search the analytics system's own report catalogue."""
        return await analytics.catalog(
            ctx.deps.analytics_http, ctx.deps.cfg.matomo, search, offset
        )

    @agent.tool
    async def analytics_query(
        ctx: RunContext[Deps],
        method: str,
        params: dict[str, Any] | None = None,
        save_as: str | None = None,
    ) -> dict[str, Any]:
        """Call a discovered analytics report.

        Typical time parameters are period=day with date=today, or period=range
        with date=start,end. filter_limit=-1 requests all rows. Keep each
        metric's meaning from the report metadata; do not reinterpret it as
        records from another source.
        """
        return await analytics.query(
            ctx.deps.analytics_http,
            ctx.deps.cfg.matomo,
            method,
            params,
            save_as,
        )

    @agent.tool
    async def logs_overview(
        ctx: RunContext[Deps], minutes: int = 10
    ) -> dict[str, Any]:
        """Compare adjacent log windows for every service using only counts.

        Returns volume, levels, write activity, silence and numbers of line
        shapes that appeared or disappeared. These are navigation signals; use
        logs_search for actual lines.
        """
        return await logs.overview(ctx.deps.logs_http, minutes)

    @agent.tool
    async def logs_search(
        ctx: RunContext[Deps],
        service: str,
        minutes: int = 15,
        pattern: str = "",
        until_minutes_ago: int = 0,
    ) -> dict[str, Any]:
        """Search one service's bounded log window with a regular expression.

        An empty pattern shows the most recent lines. until_minutes_ago selects
        an earlier window. Results include a file and line numbers for context.
        """
        return await logs.search(
            ctx.deps.logs_http,
            service,
            minutes,
            pattern,
            until_minutes_ago,
        )

    @agent.tool_plain
    def logs_context(
        file: str, line_no: int, before: int = 3, after: int = 3
    ) -> dict[str, Any]:
        """Read bounded lines around one match in a downloaded log."""
        return logs.context(file, line_no, before, after)

    @agent.tool
    async def feed_list(
        ctx: RunContext[Deps],
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """List the master-data files currently published by the ERP."""
        return feed.list_files(ctx.deps.cfg.feed)

    @agent.tool
    async def feed_read(
        ctx: RunContext[Deps],
        name: str,
        offset: int = 0,
        save_as: str | None = None,
    ) -> dict[str, Any]:
        """Read a master-data file, or import a CSV into a local table."""
        return feed.read_file(
            ctx.deps.cfg.feed, name, offset=offset, save_as=save_as
        )

    @agent.tool_plain
    def table_list() -> list[dict[str, Any]]:
        """List local tables with fields, provenance and completeness."""
        return tables.list_tables()

    @agent.tool_plain
    def table_sample(
        table: str,
        fields: list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Inspect selected fields from a bounded table window."""
        return tables.sample(table, fields, limit, offset)

    @agent.tool_plain
    def table_filter(table: str, where: list[str], into: str) -> dict[str, Any]:
        """Keep rows matching all generic conditions in a new table.

        Conditions use field=value, !=, >, <, >=, <=, or field~text.
        """
        return tables.filter_rows(table, where, into)

    @agent.tool_plain
    def table_join(
        left: str,
        right: str,
        left_key: str,
        right_key: str,
        into: str,
        how: str = "inner",
    ) -> dict[str, Any]:
        """Join two tables by one key; how is inner, left, or anti."""
        return tables.join(left, right, left_key, right_key, into, how)

    @agent.tool_plain
    def table_group(
        table: str,
        group_by: list[str],
        measures: list[str] | None = None,
    ) -> dict[str, Any]:
        """Group rows with count, sum:field, avg:field, min:field or max:field."""
        return tables.group(table, group_by, measures)

    @agent.tool_plain
    def table_compare(
        left: str,
        right: str,
        keys: list[str],
        measures: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compare the same grouped measures across two local tables."""
        return tables.compare(left, right, keys, measures)


TOOLBOX = Toolbox(deps_type=Deps, deps=deps, register=register)
"""Blair, as the shared loop needs to see it: a type, its clients, its tools."""
