"""The log tools: download to disk, then search the file.

Two things are being protected. The first is the context: a `logs_search` that
returned matching lines directly once came back with a 13 KB PHP stack trace, the
model produced nothing at all, and the run ended. Nothing here may return
unbounded text.

The second is the filesystem. `grep` and `slice` take a filename from the model,
so the resolution has to be provably confined to one directory — a traversal is
not a hypothetical when the argument is generated.
"""

import httpx
import pytest

from roles.angel.tools import logs
from tests.angel.conftest import transport


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    """Each test gets its own directory, so nothing leaks between them and the
    developer's real downloads are never touched."""
    monkeypatch.setattr(logs, "LOG_DIR", tmp_path)
    return tmp_path


def _loki(streams) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"result": streams}})

    return httpx.AsyncClient(base_url="https://loki.test", transport=transport(handler))


def _write(workspace, name: str, lines: list[str]) -> str:
    (workspace / name).write_text("\n".join(lines) + "\n")
    return name


# ── fetch ────────────────────────────────────────────────────────────────────


async def test_fetch_returns_facts_and_not_one_line_of_log(workspace):
    """The whole point: volume lands on disk, the conversation gets a summary."""
    async with _loki(
        [{"values": [["1785434776691616796", "a secret-looking log line"]]}]
    ) as http:
        result = await logs.fetch(http, "camel", 60)

    assert result["lines"] == 1
    assert "a secret-looking log line" not in str(result)
    assert (
        (workspace / result["file"])
        .read_text()
        .strip()
        .endswith("a secret-looking log line")
    )


async def test_fetch_rewrites_nanosecond_stamps_into_readable_time(workspace):
    """A run was comparing raw nanosecond integers against order dates. The file
    carries an ISO stamp so the arithmetic is not invented."""
    async with _loki([{"values": [["1785434776691616796", "x"]]}]) as http:
        result = await logs.fetch(http, "camel", 60)

    assert result["from"].startswith("2026-07-30T")
    assert "2026-07-30T" in (workspace / result["file"]).read_text()


async def test_fetch_orders_oldest_first_across_streams(workspace):
    """Loki returns newest-first, per stream. A file that jumps around in time is
    unreadable and makes "when did this start" unanswerable."""
    async with _loki(
        [
            {"values": [["300", "third"], ["100", "first"]]},
            {"values": [["200", "second"]]},
        ]
    ) as http:
        result = await logs.fetch(http, "camel", 60)

    body = (workspace / result["file"]).read_text().splitlines()
    assert [line.split()[-1] for line in body] == ["first", "second", "third"]


async def test_fetch_reports_an_empty_window_without_crashing(workspace):
    async with _loki([]) as http:
        result = await logs.fetch(http, "camel", 60)

    assert result["lines"] == 0
    assert result["from"] is None and result["to"] is None


async def test_fetch_surfaces_a_loki_failure(workspace):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="too many outstanding requests")

    async with httpx.AsyncClient(
        base_url="https://loki.test", transport=transport(handler)
    ) as http:
        result = await logs.fetch(http, "camel", 60)

    assert result["error"] == "HTTP 503"
    assert "outstanding" in result["body"]


# ── grep ─────────────────────────────────────────────────────────────────────


def test_grep_reports_the_true_count_even_when_it_shows_fewer(workspace):
    """ "How often" is a cheaper question than "show me", and answering it without
    returning everything is the reason this tool exists."""
    name = _write(workspace, "camel.log", [f"line {i} ERROR" for i in range(200)])

    result = logs.grep(name, "ERROR")

    assert result["matches"] == 200
    assert result["shown"] == logs.MAX_MATCHES
    assert f"{200 - logs.MAX_MATCHES} more" in result["note"]


def test_grep_truncates_a_stack_trace_instead_of_returning_it(workspace):
    """The 13 KB line that ended a run."""
    name = _write(workspace, "php.log", ["PHP Fatal error: " + "x" * 13_000])

    result = logs.grep(name, "Fatal")

    assert len(result["lines"][0]["line"]) <= logs.MAX_LINE_CHARS + 1


def test_grep_gives_line_numbers_so_a_hit_can_be_read_around(workspace):
    name = _write(workspace, "camel.log", ["a", "b", "needle", "d"])

    result = logs.grep(name, "needle")

    assert result["lines"] == [{"line_no": 3, "line": "needle"}]


def test_grep_is_case_insensitive_by_default_and_can_be_told_otherwise(workspace):
    name = _write(workspace, "camel.log", ["ERROR here", "error there"])

    assert logs.grep(name, "error")["matches"] == 2
    assert logs.grep(name, "error", ignore_case=False)["matches"] == 1


def test_a_bad_regex_is_explained_not_raised(workspace):
    """A model writes `[unclosed`. Raising would end the investigation."""
    name = _write(workspace, "camel.log", ["x"])

    result = logs.grep(name, "[unclosed")

    assert "bad pattern" in result["error"]


def test_grep_caps_what_a_caller_can_ask_for(workspace):
    """max_matches is the model's to choose, but not without limit."""
    name = _write(workspace, "camel.log", ["hit"] * 500)

    result = logs.grep(name, "hit", max_matches=10_000)

    assert result["shown"] == logs.MAX_MATCHES


def test_grep_on_a_file_never_fetched_says_to_fetch_it(workspace):
    result = logs.grep("nothing.log", "x")

    assert "logs_fetch" in result["error"]


# ── the sandbox ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "escape",
    [
        "../../../etc/passwd",
        "/etc/passwd",
        "..%2F..%2Fsecrets.env",
        "subdir/../../.env",
    ],
)
def test_no_filename_can_escape_the_log_directory(workspace, escape):
    """The filename comes from the model. Both readers must confine it."""
    assert "error" in logs.grep(escape, "x")
    assert "error" in logs.slice_(escape, 1, 5)


def test_a_real_file_outside_the_directory_stays_unreachable(workspace, tmp_path):
    outside = tmp_path.parent / "outside.log"
    outside.write_text("a genuine secret\n")

    assert "error" in logs.grep("../outside.log", "secret")


# ── slice and files ──────────────────────────────────────────────────────────


def test_slice_reads_the_window_asked_for(workspace):
    name = _write(workspace, "camel.log", [f"l{i}" for i in range(1, 51)])

    result = logs.slice_(name, start=10, count=3)

    assert [row["line_no"] for row in result["lines"]] == [10, 11, 12]
    assert result["lines"][0]["line"] == "l10"


def test_slice_past_the_end_returns_nothing_rather_than_failing(workspace):
    name = _write(workspace, "camel.log", ["only"])

    result = logs.slice_(name, start=999, count=5)

    assert result["returned"] == 0


def test_slice_has_a_ceiling_of_its_own(workspace):
    """`count=100000` would put the whole file back in the context."""
    name = _write(workspace, "camel.log", [f"l{i}" for i in range(500)])

    assert logs.slice_(name, start=1, count=100_000)["returned"] == logs.MAX_SLICE_LINES


def test_files_lists_what_has_been_downloaded(workspace):
    _write(workspace, "camel-60m.log", ["a", "b", "c"])
    _write(workspace, "gateway-60m.log", ["a"])

    listed = logs.files()

    assert [f["file"] for f in listed] == ["camel-60m.log", "gateway-60m.log"]
    assert listed[0]["lines"] == 3


def test_files_is_empty_before_anything_is_fetched(workspace, monkeypatch):
    monkeypatch.setattr(logs, "LOG_DIR", workspace / "not-created-yet")

    assert logs.files() == []


# ── declared boundaries ──────────────────────────────────────────────────────


async def test_fetch_declares_a_complete_window(workspace):
    async with _loki([{"values": [["100", "a"], ["200", "b"]]}]) as http:
        result = await logs.fetch(http, "camel", 60)

    assert result["complete"] is True
    assert "truncated" not in result


async def test_fetch_says_when_it_hit_its_ceiling(workspace, monkeypatch):
    """Loki returns newest-first, so hitting the cap loses the OLDEST end. Not
    saying so is how "the log starts at 14:02" becomes a false fact about when
    something began."""
    monkeypatch.setattr(logs, "MAX_FETCH_LINES", 3)

    async with _loki([{"values": [[str(i), f"l{i}"] for i in range(3)]}]) as http:
        result = await logs.fetch(http, "camel", 60)

    assert result["complete"] is False
    assert "OLDEST" in result["truncated"]


def test_a_clipped_line_says_it_was_clipped_and_how_long_it_really_is(workspace):
    name = _write(workspace, "php.log", ["Fatal: " + "x" * 5000])

    hit = logs.grep(name, "Fatal")["lines"][0]

    assert hit["clipped"] is True
    assert hit["line_chars"] == 5007


def test_a_short_line_carries_no_clipped_marker(workspace):
    name = _write(workspace, "camel.log", ["short"])

    assert "clipped" not in logs.grep(name, "short")["lines"][0]


def test_read_line_reaches_the_tail_of_a_long_line(workspace):
    """The escape hatch the module docstring used to promise but not provide."""
    name = _write(workspace, "php.log", ["HEAD" + "x" * 1000 + "TAIL"])

    first = logs.read_line(name, 1, char_offset=0, max_chars=100)
    assert first["complete"] is False
    assert first["text"].startswith("HEAD")

    rest = logs.read_line(name, 1, char_offset=first["next_offset"], max_chars=2000)
    assert rest["complete"] is True
    assert rest["text"].endswith("TAIL")


def test_read_line_reports_the_real_length(workspace):
    name = _write(workspace, "php.log", ["y" * 900])

    assert logs.read_line(name, 1)["line_chars"] == 900


def test_read_line_past_the_end_is_an_error_not_an_empty_string(workspace):
    """An empty string would read as "that line is blank"."""
    name = _write(workspace, "camel.log", ["only"])

    assert "past the end" in logs.read_line(name, 99)["error"]


@pytest.mark.parametrize("escape", ["../../../etc/passwd", "/etc/passwd"])
def test_read_line_is_confined_to_the_log_directory(workspace, escape):
    assert "error" in logs.read_line(escape, 1)


# ── overview ─────────────────────────────────────────────────────────────────


def _windowed_loki(by_window):
    """A Loki that answers differently for the current and the previous window.

    `since` means "up to now"; `start`/`end` mean an explicit range. Keying on
    which arrived is what lets a test tell the two windows apart at all — and is
    exactly the distinction the tool failed to make.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/label/service/values"):
            return httpx.Response(200, json={"data": ["camel"]})
        key = "current" if "since" in request.url.params else "previous"
        lines = by_window[key]
        stamp = "1785531600000000000"
        return httpx.Response(
            200,
            json={
                "data": {
                    "result": [{"values": [[stamp, line] for line in lines]}],
                }
            },
        )

    return httpx.AsyncClient(base_url="https://loki.test", transport=transport(handler))


async def test_overview_compares_against_a_window_that_excludes_the_present():
    """The defect that made this tool useless without ever failing: the previous
    window was fetched as `minutes * 2`, i.e. [now-2N, now] — a superset of the
    current one. A shape present now was therefore present "before" by
    construction, and across two campaigns 19 calls produced 83 counts of which
    every one was zero. The tool built to answer "what changed" could not."""
    http = _windowed_loki(
        {
            "current": ['{"event":"reconciliation_change","operation":"delete"}'],
            "previous": ['{"event":"reconciliation_change","operation":"update"}'],
        }
    )
    async with http:
        result = await logs.overview(http, minutes=10)

    camel = next(s for s in result["services"] if s["service"] == "camel")
    assert camel["new_templates"] == 1, "a shape absent before and present now"
    assert "delete" in str(camel["new"])


async def test_overview_reports_nothing_new_when_nothing_is_new():
    """The other half: the comparison must not cry wolf on a steady service, or
    every line becomes news and none of it is."""
    steady = ['{"event":"reconciliation_change","operation":"update"}']
    http = _windowed_loki({"current": steady, "previous": steady})
    async with http:
        result = await logs.overview(http, minutes=10)

    camel = next(s for s in result["services"] if s["service"] == "camel")
    assert camel["new_templates"] == 0


async def test_the_previous_window_does_not_overwrite_the_current_download(workspace):
    """`logs_grep` runs against the file this left behind. If the comparison
    fetch reused the name, a later grep would silently search the wrong window."""
    http = _windowed_loki({"current": ["now one", "now two"], "previous": ["old one"]})
    async with http:
        result = await logs.overview(http, minutes=10)

    camel = next(s for s in result["services"] if s["service"] == "camel")
    assert camel["file"] != camel["compared_with"]
    assert (workspace / camel["file"]).read_text().count("now") == 2


async def test_fetch_asks_loki_for_an_earlier_window_explicitly(workspace):
    """`since` can only say "up to now", so a disjoint earlier window has to be
    expressed as an explicit start and end."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"data": {"result": []}})

    http = httpx.AsyncClient(base_url="https://loki.test", transport=transport(handler))
    async with http:
        await logs.fetch(http, "camel", 10, until_minutes_ago=10)

    assert "since" not in seen
    assert int(seen["end"]) - int(seen["start"]) == 10 * 60 * 1_000_000_000

