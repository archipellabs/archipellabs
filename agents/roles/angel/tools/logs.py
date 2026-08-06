"""Logs as files on disk, searched — not pasted into the conversation.

The tool this replaces returned matching lines straight into the context, and a
run died of it: one `logs_search` came back with a 13 KB PHP stack trace, the
model produced nothing at all, and the investigation ended. Two returns from that
tool were 17 KB of the run's 20 KB total.

That is not how anyone reads logs. You pull them down once and then grep, and the
few lines you keep are what you actually think about. So `fetch` downloads a
service's window to a file and returns only *facts about* it — how many lines,
what span, how big — and `grep`, `slice` and `count` work over the file with
bounded output. Volume stays on disk, where volume belongs.

The label set is fixed to the company's own services, so an agent cannot reach
the simulator's logs — those belong to the instrument that produces the symptom
and would be the answer key rather than evidence.

**No shell.** `grep` here is Python doing grep's job over a directory this module
owns. Handing a real shell to a model running on someone's machine buys realism
we do not need and a class of accident we cannot take back; the agent gets the
*capability* to search files, not the ability to run commands.
"""

import os
import pathlib
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import LokiConfig
from roles.angel.tools import workspace

LOG_DIR = pathlib.Path(
    os.getenv("AGENT_LOG_DIR") or pathlib.Path(__file__).resolve().parents[1] / "logs"
)
"""Where downloads live when no investigation is running."""


def _root() -> pathlib.Path:
    """This run's log directory, or the shared one outside a run.

    Per run, so one investigation never greps a window another one downloaded —
    the filenames carry a service and a span but not whose question produced
    them. See `workspace`."""
    return workspace.logs() or LOG_DIR


MAX_FETCH_LINES = 5000
"""How many lines one fetch pulls down. Loki's own cap is per query; this is the
size of the haystack we are willing to keep, and it is generous because nothing
here goes into the context."""

MAX_MATCHES = 40
"""Matches returned by one grep. Past this you want a narrower pattern, and
saying how many were found is more useful than shipping them all."""

MAX_LINE_CHARS = 300
"""How much of a single line `grep` and `slice` show.

A stack trace is one 13 KB "line" and returning it whole once ended a run. A
clipped line is marked `clipped` with its true length, and `read_line` fetches
the remainder from a character offset — the escape hatch this docstring used to
promise `slice` provided, wrongly."""

MAX_SLICE_LINES = 100
"""A context window, not another log download pasted into the conversation."""


def client(cfg: LokiConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=cfg.base_url, timeout=60.0)


async def services_logging(http: httpx.AsyncClient) -> list[str]:
    """Which systems are sending logs at all — the menu for `fetch`."""
    r = await http.get("/loki/api/v1/label/service/values")
    r.raise_for_status()
    return sorted(r.json().get("data", []) or [])


def _path(service: str, minutes: int, until_minutes_ago: int = 0) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", service)
    if until_minutes_ago:
        return _root() / f"{safe}-{minutes}m-before{until_minutes_ago}m.log"
    return _root() / f"{safe}-{minutes}m.log"


def _resolve(name: str) -> pathlib.Path | None:
    """A file inside this run's directory, or nothing. Never escapes it."""
    candidate = (_root() / pathlib.Path(name).name).resolve()
    if candidate.parent != _root().resolve() or not candidate.is_file():
        return None
    return candidate


async def fetch(
    http: httpx.AsyncClient,
    service: str,
    minutes: int = 60,
    *,
    until_minutes_ago: int = 0,
) -> dict[str, Any]:
    """Download one service's recent logs to a file. Returns facts, not content.

    `until_minutes_ago` ends the window early, so `minutes=10,
    until_minutes_ago=10` is the ten minutes *before* the last ten. Loki's
    `since` can only express "up to now", and a comparison needs two windows that
    do not overlap — see `overview`, where using `since` twice made every
    comparison vacuous.
    """
    params: dict[str, str] = {
        "query": f'{{service="{service}"}}',
        "limit": str(MAX_FETCH_LINES),
    }
    if until_minutes_ago:
        end = datetime.now(UTC).timestamp() - until_minutes_ago * 60
        params["end"] = str(int(end * 1_000_000_000))
        params["start"] = str(int((end - minutes * 60) * 1_000_000_000))
    else:
        params["since"] = f"{minutes}m"

    r = await http.get("/loki/api/v1/query_range", params=params)
    if r.status_code >= 400:
        return {
            "service": service,
            "error": f"HTTP {r.status_code}",
            "body": r.text[:200],
        }

    entries: list[tuple[str, str]] = []
    for stream in r.json().get("data", {}).get("result", []):
        for ts, line in stream.get("values", []):
            entries.append((ts, line.rstrip("\n")))
    entries.sort(key=lambda item: item[0])

    _root().mkdir(parents=True, exist_ok=True)
    path = _path(service, minutes, until_minutes_ago)
    with path.open("w") as handle:
        for ts, line in entries:
            handle.write(f"{_stamp(ts)} {line}\n")

    complete = len(entries) < MAX_FETCH_LINES
    result: dict[str, Any] = {
        "file": path.name,
        "service": service,
        "lines": len(entries),
        "bytes": path.stat().st_size,
        "from": _stamp(entries[0][0]) if entries else None,
        "to": _stamp(entries[-1][0]) if entries else None,
        # Loki returns newest-first and we sort ascending, so hitting the cap
        # means the OLDEST part of the window is missing. Saying "5000 lines"
        # without that is how "the log starts at 14:02" becomes a false fact
        # about when something began.
        "complete": complete,
        "note": "use logs_grep to search it; nothing was read into this conversation",
    }
    if not complete:
        result["truncated"] = (
            f"hit the {MAX_FETCH_LINES}-line ceiling, so the window is partial and "
            f"its OLDEST end is missing — narrow `minutes` to see earlier lines"
        )
    return result


def _stamp(nanos: str) -> str:
    """Loki's nanosecond epoch as something a person can compare against an order
    date — the raw integer is unreadable and invites bad arithmetic."""
    try:
        return datetime.fromtimestamp(int(nanos) / 1e9, UTC).isoformat(
            timespec="seconds"
        )
    except (ValueError, OSError):
        return nanos


def _clip_line(number: int, line: str) -> dict[str, Any]:
    """One line for display, saying so when there is more of it.

    A silently clipped line is a small version of the same lie as a silently
    truncated result: it reads as the whole line. `logs_read` fetches the rest.
    """
    stripped = line.rstrip("\n")
    row: dict[str, Any] = {"line_no": number, "line": stripped[:MAX_LINE_CHARS]}
    if len(stripped) > MAX_LINE_CHARS:
        row["line_chars"] = len(stripped)
        row["clipped"] = True
    return row


def grep(
    file: str, pattern: str, max_matches: int = MAX_MATCHES, ignore_case: bool = True
) -> dict[str, Any]:
    """Matching lines from a downloaded log file, with their line numbers."""
    path = _resolve(file)
    if path is None:
        return {"file": file, "error": "no such file; call logs_fetch first"}
    try:
        matcher = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        return {"file": file, "error": f"bad pattern: {exc}"}

    hits: list[dict[str, Any]] = []
    total = 0
    for number, line in enumerate(path.open(), start=1):
        if matcher.search(line):
            total += 1
            if len(hits) < max(1, min(max_matches, MAX_MATCHES)):
                hits.append(_clip_line(number, line))

    result: dict[str, Any] = {"file": file, "matches": total, "shown": len(hits)}
    if total > len(hits):
        result["note"] = f"{total - len(hits)} more; narrow the pattern or read a slice"
    result["lines"] = hits
    return result


def read_line(
    file: str, line_no: int, char_offset: int = 0, max_chars: int = MAX_LINE_CHARS
) -> dict[str, Any]:
    """Read one line, from a character offset — how a long line is actually read.

    `grep` and `slice` both clip at MAX_LINE_CHARS, so before this existed the
    tail of a 13 KB stack trace was unreachable by any tool while the module
    docstring claimed `slice` could fetch it. This is that claim made true.
    """
    path = _resolve(file)
    if path is None:
        return {"file": file, "error": "no such file; call logs_fetch first"}

    for number, line in enumerate(path.open(), start=1):
        if number != line_no:
            continue
        stripped = line.rstrip("\n")
        chunk = stripped[char_offset : char_offset + max(1, min(max_chars, 2000))]
        read_to = char_offset + len(chunk)
        result: dict[str, Any] = {
            "file": file,
            "line_no": line_no,
            "line_chars": len(stripped),
            "offset": char_offset,
            "returned_chars": len(chunk),
            "complete": read_to >= len(stripped),
            "text": chunk,
        }
        if not result["complete"]:
            result["next_offset"] = read_to
        return result
    return {"file": file, "error": f"line {line_no} is past the end of the file"}


def slice_(file: str, start: int = 1, count: int = 20) -> dict[str, Any]:
    """Read a window of a log file by line number — the `less` to grep's search."""
    path = _resolve(file)
    if path is None:
        return {"file": file, "error": "no such file; call logs_fetch first"}
    count = max(1, min(count, MAX_SLICE_LINES))
    out: list[dict[str, Any]] = []
    for number, line in enumerate(path.open(), start=1):
        if number < start:
            continue
        if len(out) >= count:
            break
        out.append(_clip_line(number, line))
    return {"file": file, "start": start, "returned": len(out), "lines": out}


def files() -> list[dict[str, Any]]:
    """Downloaded log files and their size, without reading their contents."""
    if not _root().is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(_root().glob("*.log")):
        with path.open() as handle:
            lines = sum(1 for _ in handle)
        out.append({"file": path.name, "lines": lines, "bytes": path.stat().st_size})
    return out


# ── triage: what changed, rather than where the word ERROR is ────────────────

TEMPLATE_NOISE = (
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b"), "<uuid>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\S*"), "<ts>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<hex>"),
    (re.compile(r"\b\d+\b"), "<n>"),
)

LEVELS = ("ERROR", "WARN", "FATAL", "CRITICAL", "INFO", "DEBUG")


def _template(line: str) -> str:
    """A log line with its variable parts blanked, so two occurrences match.

    `delivery row 21 updated: … @ 5.00` and `delivery row 22 updated: … @ 8.00`
    become one shape. Counting shapes is what makes "this kind of line is new"
    answerable without knowing in advance how anyone worded it.
    """
    shaped = line
    for pattern, placeholder in TEMPLATE_NOISE:
        shaped = pattern.sub(placeholder, shaped)
    return shaped.strip()[:MAX_LINE_CHARS]


def _summarise(path: pathlib.Path) -> dict[str, Any]:
    levels: dict[str, int] = {}
    templates: dict[str, int] = {}
    writes = 0
    total = 0
    for line in path.open():
        total += 1
        for level in LEVELS:
            if f" {level} " in line or f"[{level}]" in line:
                levels[level] = levels.get(level, 0) + 1
                break
        if any(verb in line for verb in ("POST ", "PATCH ", "DELETE ", "PUT ")):
            writes += 1
        shape = _template(line)
        templates[shape] = templates.get(shape, 0) + 1
    return {"lines": total, "levels": levels, "writes": writes, "templates": templates}


def patterns(file: str, max_patterns: int = 20) -> dict[str, Any]:
    """The most frequent normalized line shapes in one downloaded log."""
    path = _resolve(file)
    if path is None:
        return {"file": file, "error": "no such file; call logs_fetch first"}
    summary = _summarise(path)
    ranked = sorted(
        summary["templates"].items(), key=lambda item: item[1], reverse=True
    )
    shown = ranked[: max(1, min(max_patterns, MAX_MATCHES))]
    return {
        "file": file,
        "lines": summary["lines"],
        "patterns": [
            {"count": count, "template": template} for template, count in shown
        ],
    }


async def overview(
    http: httpx.AsyncClient, minutes: int = 10, compare_previous: bool = True
) -> dict[str, Any]:
    """Every service's recent activity, and what is NEW against the window before.

    The question an incident actually asks is "what changed", not "where is the
    word ERROR" — a run grepped `ERROR|CRITICAL`, found nothing, and reported
    that nothing was wrong during an outage that logs no errors at all. Novelty
    is mechanical: a line shape absent from the previous window and present in
    this one gets surfaced without anyone knowing to look for it.

    Reports what it *saw*, never what it means. A new template is a fact.
    """
    try:
        services = await services_logging(http)
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"cannot list log services: {type(exc).__name__}: {exc}"}
    out: dict[str, Any] = {"window_minutes": minutes, "services": []}
    for service in services:
        now = await fetch(http, service, minutes)
        if "error" in now:
            out["services"].append({"service": service, **now})
            continue
        path = _resolve(now["file"])
        if path is None:
            continue
        summary = _summarise(path)
        entry: dict[str, Any] = {
            "service": service,
            "lines": summary["lines"],
            "levels": summary["levels"],
            "writes": summary["writes"],
            "from": now.get("from"),
            "to": now.get("to"),
            "file": now["file"],
        }
        if summary["lines"] == 0:
            entry["silent"] = True

        if compare_previous and summary["lines"]:
            # The window BEFORE this one — [now-2N, now-N], not [now-2N, now].
            # Fetching `minutes * 2` made the comparison set a superset of the
            # current one, so a shape present now was present "before" by
            # construction: across two campaigns, 19 calls returned 83 counts and
            # every single one was zero. The tool built to answer "what changed"
            # could not report a change. Its own file, so a later grep of the
            # current window still finds what it expects.
            before = await fetch(
                http,
                service,
                minutes,
                until_minutes_ago=minutes,
            )
            before_path = _resolve(before.get("file", ""))
            if before_path is not None:
                older = _summarise(before_path)
                fresh = [
                    shape
                    for shape in summary["templates"]
                    if shape not in older["templates"]
                ]
                entry["previous_lines"] = older["lines"]
                entry["new_templates"] = len(fresh)
                entry["new"] = fresh[:5]
                entry["compared_with"] = before.get("file")
            elif "error" in before:
                entry["comparison_error"] = before["error"]

        out["services"].append(entry)

    out["note"] = "line shapes only; a new template is a fact, not a diagnosis"
    return out


async def query(
    http: httpx.AsyncClient,
    service: str,
    minutes: int = 60,
    pattern: str = "",
    max_matches: int = MAX_MATCHES,
) -> dict[str, Any]:
    """Fetch a service's window and search it in one call.

    The fetch/grep/slice sequence is right for a deep read and too slow for
    triage: three round trips before the first fact. This is the same primitives
    with the ceremony removed, and it leaves the file behind for `logs_slice`.
    """
    fetched = await fetch(http, service, minutes)
    if "error" in fetched:
        return fetched
    if not pattern:
        return fetched
    found = grep(fetched["file"], pattern, max_matches=max_matches)
    return {**fetched, **found}
