"""The analyst — a simulated employee that investigates and reports.

Read-only, on purpose. This first agent exists to answer one question: **is the
incident discoverable at all from the evidence the company actually keeps?** If a
role holding every read credential cannot find it, that is a finding about the
company's observability, and narrowing permissions afterwards would measure
nothing. It also produces the reference trace of a good investigation, which is a
fairer rubric for later runs than one written in advance.

The toolset is a property of the identity, not of the code. Every tool below is
registered for this profile; a business-only or technical-only role is the same
module with a shorter list, which is what makes the access gradient a
configuration rather than a rewrite.

**What is left here is only that.** Building the model, driving the loop,
counting what it spent and writing down what it did were this file's too, and
were the same code in Blair — they are `core.harness.pydantic_ai` now. A
`Toolbox` is the whole of what this employee hands it: a type, its clients, and
these registrations.
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
from roles.angel.tools import analytics, data, feed, logs, shop, workspace


@dataclass
class Deps:
    """Live clients and credentials. Never visible to the model."""

    cfg: Config
    shop_http: httpx.AsyncClient
    matomo_http: httpx.AsyncClient
    loki_http: httpx.AsyncClient


@contextlib.asynccontextmanager
async def deps(cfg: Config, workdir: pathlib.Path) -> AsyncIterator[Deps]:
    """This run's clients, and this run's scratch, for exactly this run.

    Both in one context manager, because both are the investigation's and
    neither outlives it. The scratch used to be bound in a `try/finally` one
    layer up and the clients in an `async with` one layer down, which is two
    places to forget.

    **The scratch is per run.** Shared, the datasets and downloads of the run
    before were listed to the run after, and a name like `complaint_carts` hands
    over a hypothesis rather than data.
    """
    token = workspace.use(run_of(workdir))
    try:
        async with (
            shop.client(cfg.shop) as shop_http,
            analytics.client(cfg.matomo) as matomo_http,
            logs.client(cfg.loki) as loki_http,
        ):
            yield Deps(
                cfg=cfg,
                shop_http=shop_http,
                matomo_http=matomo_http,
                loki_http=loki_http,
            )
    finally:
        workspace.release(token)


def register(agent: Agent[Deps, Answer | Refusal]) -> None:
    """Every tool this identity holds, attached to one run's agent.

    Closures rather than free functions, because each one needs the agent to
    decorate it and the deps to reach the company. What they are *about* lives
    in `src.tools`, which Dana shares verbatim — this file is the list, not the
    implementation.
    """

    @agent.tool_plain
    def thought(thought: str = "") -> str:
        """Record one step of your reasoning before deciding what to check next."""
        # Gemma-class models emit reasoning as a tool call whether or not one is
        # offered; without this the run dies on "tool 'thought' exceeded max
        # retries" having done no work. Giving it the scratchpad it wants costs
        # nothing and puts the reasoning in the transcript, which is the part
        # worth reading when judging an investigation.
        #
        # The argument is OPTIONAL, and that is the whole point. Required, it
        # killed two of three runs in a campaign: gemma called `thought` with
        # `''` and then `{}`, pydantic rejected "field required" twice, and the
        # run died at its fourth call having investigated nothing. A scratchpad
        # that refuses an empty note and takes the process down with it is the
        # same defect as everything else here — a tool turning a harmless
        # mistake into a dead end.
        return "noted"

    @agent.tool
    async def shop_resources(ctx: RunContext[Deps]) -> list[dict[str, Any]]:
        """List every resource in the shop's API, with what each one holds."""
        return await shop.resources(ctx.deps.shop_http)

    @agent.tool
    async def shop_schema(ctx: RunContext[Deps], resource: str) -> dict[str, Any]:
        """The field names of one shop resource. Read this before querying it."""
        return await shop.schema(ctx.deps.shop_http, resource)

    @agent.tool
    async def shop_get(
        ctx: RunContext[Deps],
        resource: str,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        sort: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        into: str | None = None,
    ) -> dict[str, Any]:
        """Read a shop resource.

          fields=["id","date_add"]             select columns
          filters={"active":"1"}               select rows
          filters={"date_add":"[2026-01-01 00:00:00,2026-01-01 23:59:59]"}
          sort=["id_DESC"], limit=25, offset=100

        Results declare `complete`, `next_offset` and `last_offset`, and date
        windows say which timezone they use. `into="name"` also saves the rows
        for the data tools.
        """
        params = shop.query_params(fields, filters, sort, limit, offset)
        return await shop.get(ctx.deps.shop_http, resource, params, into=into)

    @agent.tool
    async def analytics_reports(ctx: RunContext[Deps]) -> Any:
        """Every analytics report available, with its method and dimensions."""
        return await analytics.reports(ctx.deps.matomo_http, ctx.deps.cfg.matomo)

    @agent.tool
    async def analytics_get(
        ctx: RunContext[Deps],
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call one analytics report by its method name.

          {"period": "day", "date": "today"}
          {"period": "range", "date": "2026-01-01,2026-01-31"}
          {"filter_limit": 50, "filter_offset": 0}     paging

        Counts are visits (sessions), not people or orders.
        `filter_limit=-1` requests all rows.
        """
        return await analytics.get(ctx.deps.matomo_http, ctx.deps.cfg.matomo, method, params)

    @agent.tool
    async def logs_services(ctx: RunContext[Deps]) -> list[str]:
        """Which company systems are currently sending logs."""
        return await logs.services_logging(ctx.deps.loki_http)

    @agent.tool
    async def logs_fetch(
        ctx: RunContext[Deps], service: str, minutes: int = 60
    ) -> dict[str, Any]:
        """Download one system's recent logs to a file without reading them.

        Returns the filename, line count and time span. Use logs_grep,
        logs_patterns or logs_slice to inspect the downloaded file.
        """
        return await logs.fetch(ctx.deps.loki_http, service, minutes)

    @agent.tool
    async def logs_overview(ctx: RunContext[Deps], minutes: int = 10) -> dict[str, Any]:
        """Summarize current and previous log windows for every service.

        Reports line volume, levels, write counts, silence, and line shapes
        absent from the previous window.
        """
        return await logs.overview(ctx.deps.loki_http, minutes)

    @agent.tool
    async def logs_query(
        ctx: RunContext[Deps], service: str, minutes: int = 60, pattern: str = ""
    ) -> dict[str, Any]:
        """Fetch one system's logs and search them in a single call.

        `pattern` is a regular expression. Matching lines are bounded and
        shown, with the full count and line numbers. The downloaded file remains
        available to logs_slice and logs_read.
        """
        return await logs.query(ctx.deps.loki_http, service, minutes, pattern)

    @agent.tool_plain
    def logs_patterns(file: str, max_patterns: int = 20) -> dict[str, Any]:
        """The most frequent normalized line shapes in a downloaded log."""
        return logs.patterns(file, max_patterns=max_patterns)

    @agent.tool_plain
    def logs_files() -> list[dict[str, Any]]:
        """The log files downloaded during this investigation."""
        return logs.files()

    @agent.tool_plain
    def logs_grep(
        file: str,
        pattern: str,
        max_matches: int = logs.MAX_MATCHES,
        ignore_case: bool = True,
    ) -> dict[str, Any]:
        """Search a downloaded log file with a regular expression."""
        return logs.grep(file, pattern, max_matches, ignore_case)

    @agent.tool_plain
    def logs_slice(file: str, start: int = 1, count: int = 20) -> dict[str, Any]:
        """Read a window of a log file by line number, to see around a match.

        A line longer than the display limit comes back marked `clipped` with its
        true length; use logs_read to fetch the rest of it.
        """
        return logs.slice_(file, start=start, count=count)

    @agent.tool_plain
    def logs_read(
        file: str, line_no: int, char_offset: int = 0, max_chars: int = 300
    ) -> dict[str, Any]:
        """Read one log line from a character offset — for lines too long to show.

        A stack trace is a single very long line. Read it in pieces: when
        `complete` is false, continue from `next_offset`.
        """
        return logs.read_line(
            file, line_no, char_offset=char_offset, max_chars=max_chars
        )

    @agent.tool_plain
    def data_join(
        left: str,
        right: str,
        left_key: str,
        right_key: str,
        into: str,
        how: str = "inner",
    ) -> dict[str, Any]:
        """Match two datasets on a key and save the result.

        `how` is `inner`, `left`, or `anti` (unmatched left rows only).
        Colliding right fields get an `r_` prefix. Unknown keys are refused.
        """
        return data.join(left, right, left_key, right_key, into, how)

    @agent.tool_plain
    def data_filter(dataset: str, where: list[str], into: str) -> dict[str, Any]:
        """Keep the rows matching every condition, as a new dataset.

        Conditions look like `iso_code=CA`, `id_carrier=0` or `name~wood`
        for "contains". Numbers compare as numbers.
        """
        return data.filter_(dataset, where, into)

    @agent.tool_plain
    def data_sample(
        dataset: str,
        fields: list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Read selected fields from a bounded window of a dataset."""
        return data.sample(dataset, fields, limit, offset)

    @agent.tool_plain
    def data_aggregate(
        dataset: str, group_by: list[str], measures: list[str] | None = None
    ) -> dict[str, Any]:
        """Group a dataset and measure each group.

        Measures: `count`, `sum:field`, `avg:field`, `min:field`, `max:field`.
        An empty `group_by` measures the whole dataset.
        """
        return data.aggregate(dataset, group_by, measures)

    @agent.tool_plain
    def data_compare(
        left: str, right: str, keys: list[str], measures: list[str] | None = None
    ) -> dict[str, Any]:
        """The same aggregate over two datasets, with the delta between them.

        Groups present on only one side are marked and changes are shown first.
        """
        return data.compare(left, right, keys, measures)

    @agent.tool_plain
    def data_datasets() -> list[dict[str, Any]]:
        """The datasets built during this investigation, with their shape."""
        return data.datasets()

    @agent.tool
    async def feed_list_files(ctx: RunContext[Deps]) -> list[str]:
        """The master-data files published on the ERP file drop."""
        return feed.list_files(ctx.deps.cfg.feed)

    @agent.tool
    async def feed_read_file(
        ctx: RunContext[Deps], name: str, offset: int = 0
    ) -> dict[str, Any]:
        """A master-data file from the ERP file drop, or a window of it.

        Large files come back cut short. Check `complete`: when it is false, read
        on from `next_offset` before concluding that something is not in the file.
        """
        return feed.read_file(ctx.deps.cfg.feed, name, offset=offset)


TOOLBOX = Toolbox(deps_type=Deps, deps=deps, register=register)
"""Angel, as the shared loop needs to see it: a type, its clients, its tools."""
