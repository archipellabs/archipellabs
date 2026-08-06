"""Bounded log triage: change counts, search, then local context."""

import pathlib
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import LokiConfig
from roles.blair.tools import workspace

MAX_FETCH_LINES = 5000
MAX_MATCHES = 20
MAX_LINE_CHARS = 400
MAX_CONTEXT = 21

_NOISE = (
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b"), "<uuid>"),
    (
        re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\S*"),
        "<timestamp>",
    ),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<hex>"),
    (re.compile(r"\b\d+\b"), "<number>"),
)
_QUERY_VALUE = re.compile(r"([?&][^=&\s\"]+=)[^&\s\"]+")
_HTTP_STATUS = re.compile(r'(HTTP/\d(?:\.\d)?")\s+([1-5])\d{2}(?=\s)')
_LEVELS = ("ERROR", "WARN", "FATAL", "CRITICAL", "INFO", "DEBUG")


def client(cfg: LokiConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=cfg.base_url, timeout=60.0)


async def services(http: httpx.AsyncClient) -> list[str] | dict[str, Any]:
    response = await http.get("/loki/api/v1/label/service/values")
    if response.status_code >= 400:
        return {"error": f"HTTP {response.status_code}", "body": response.text[:300]}
    try:
        return sorted(response.json().get("data", []) or [])
    except ValueError:
        return {"error": "log service directory returned non-JSON"}


async def overview(
    http: httpx.AsyncClient, minutes: int = 10
) -> dict[str, Any]:
    """Per-service volume and line-shape changes across adjacent windows."""
    listed = await services(http)
    if isinstance(listed, dict):
        return listed
    minutes = max(1, min(minutes, 1440))
    anchor = datetime.now(UTC).timestamp()
    output: list[dict[str, Any]] = []
    for service in listed:
        current = await _fetch(http, service, minutes, 0, anchor)
        previous = await _fetch(http, service, minutes, minutes, anchor)
        if "error" in current:
            output.append({"service": service, **current})
            continue
        now_summary = _summarise(current["file"])
        old_summary = _summarise(previous["file"]) if "error" not in previous else None
        entry: dict[str, Any] = {
            "service": service,
            "lines": now_summary["lines"],
            "levels": now_summary["levels"],
            "writes": now_summary["writes"],
            "silent": now_summary["lines"] == 0,
            "complete": current["complete"],
            "file": current["file"],
        }
        if old_summary is not None:
            current_shapes = set(now_summary["templates"])
            old_shapes = set(old_summary["templates"])
            entry.update(
                {
                    "previous_lines": old_summary["lines"],
                    "new_templates": len(current_shapes - old_shapes),
                    "gone_templates": len(old_shapes - current_shapes),
                    "became_active": bool(
                        now_summary["lines"] and not old_summary["lines"]
                    ),
                    "became_silent": bool(
                        old_summary["lines"] and not now_summary["lines"]
                    ),
                    "comparison_complete": bool(
                        current["complete"] and previous["complete"]
                    ),
                }
            )
        elif "error" in previous:
            entry["comparison_error"] = previous["error"]
        output.append(entry)
    return {
        "window_minutes": minutes,
        "services": output,
        "note": "template counts are navigation signals, not diagnoses",
    }


async def search(
    http: httpx.AsyncClient,
    service: str,
    minutes: int = 15,
    pattern: str = "",
    until_minutes_ago: int = 0,
) -> dict[str, Any]:
    """Download a window and return bounded regex matches with line numbers."""
    minutes = max(1, min(minutes, 1440))
    until_minutes_ago = max(0, until_minutes_ago)
    fetched = await _fetch(
        http,
        service,
        minutes,
        until_minutes_ago,
        datetime.now(UTC).timestamp(),
    )
    if "error" in fetched:
        return fetched
    try:
        matcher = re.compile(pattern, re.IGNORECASE) if pattern else None
    except re.error as exc:
        return {"service": service, "error": f"invalid regex: {exc}"}
    path = _resolve(fetched["file"])
    if path is None:
        return {"service": service, "error": "downloaded log file disappeared"}
    matches: list[dict[str, Any]] = []
    total = 0
    for line_no, line in enumerate(path.open(), start=1):
        if matcher is not None and matcher.search(line) is None:
            continue
        total += 1
        if matcher is not None and len(matches) >= MAX_MATCHES:
            # Keep counting without retaining more content.
            continue
        matches.append(_line(line_no, line))
        if matcher is None and len(matches) > MAX_MATCHES:
            matches.pop(0)
    return {
        **fetched,
        "pattern": pattern,
        "matches": total,
        "shown": len(matches),
        "lines": matches,
    }


def context(
    file: str, line_no: int, before: int = 3, after: int = 3
) -> dict[str, Any]:
    """Read bounded neighbouring lines around one search match."""
    path = _resolve(file)
    if path is None:
        return {"file": file, "error": "no such downloaded log"}
    before = min(max(0, before), MAX_CONTEXT - 1)
    after = min(max(0, after), MAX_CONTEXT - before - 1)
    start, end = max(1, line_no - before), line_no + after
    lines = [
        _line(number, line)
        for number, line in enumerate(path.open(), start=1)
        if start <= number <= end
    ]
    if not any(row["line_no"] == line_no for row in lines):
        return {"file": file, "error": f"line {line_no} is outside the file"}
    return {"file": file, "focus": line_no, "lines": lines}


async def _fetch(
    http: httpx.AsyncClient,
    service: str,
    minutes: int,
    until_minutes_ago: int,
    anchor: float,
) -> dict[str, Any]:
    escaped = service.replace("\\", "\\\\").replace('"', '\\"')
    end = anchor - until_minutes_ago * 60
    start = end - minutes * 60
    response = await http.get(
        "/loki/api/v1/query_range",
        params={
            "query": f'{{service="{escaped}"}}',
            "limit": str(MAX_FETCH_LINES),
            "start": str(int(start * 1_000_000_000)),
            "end": str(int(end * 1_000_000_000)),
        },
    )
    if response.status_code >= 400:
        return {
            "service": service,
            "error": f"HTTP {response.status_code}",
            "body": response.text[:300],
        }
    try:
        streams = response.json().get("data", {}).get("result", [])
    except ValueError:
        return {"service": service, "error": "logs returned non-JSON"}
    entries: list[tuple[str, str]] = []
    for stream in streams:
        for timestamp, line in stream.get("values", []):
            entries.append((timestamp, str(line).rstrip("\n")))
    entries.sort(key=lambda item: item[0])
    root = workspace.logs()
    root.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", service)
    suffix = f"before-{until_minutes_ago}m" if until_minutes_ago else "current"
    path = root / f"{safe}-{minutes}m-{suffix}.log"
    with path.open("w") as handle:
        for timestamp, line in entries:
            handle.write(f"{_stamp(timestamp)} {line}\n")
    return {
        "service": service,
        "file": path.name,
        "line_count": len(entries),
        "bytes": path.stat().st_size,
        "from": _stamp(entries[0][0]) if entries else None,
        "to": _stamp(entries[-1][0]) if entries else None,
        "complete": len(entries) < MAX_FETCH_LINES,
    }


def _resolve(file: str) -> pathlib.Path | None:
    root = workspace.logs().resolve()
    candidate = (root / pathlib.Path(file).name).resolve()
    if candidate.parent != root or not candidate.is_file():
        return None
    return candidate


def _summarise(file: str) -> dict[str, Any]:
    path = _resolve(file)
    if path is None:
        return {"lines": 0, "levels": {}, "writes": 0, "templates": {}}
    levels: dict[str, int] = {}
    templates: dict[str, int] = {}
    writes = 0
    total = 0
    for line in path.open():
        total += 1
        upper = line.upper()
        for level in _LEVELS:
            if f" {level} " in upper or f"[{level}]" in upper:
                levels[level] = levels.get(level, 0) + 1
                break
        if any(verb in upper for verb in ("POST ", "PUT ", "PATCH ", "DELETE ")):
            writes += 1
        template = _template(line)
        templates[template] = templates.get(template, 0) + 1
    return {"lines": total, "levels": levels, "writes": writes, "templates": templates}


def _template(line: str) -> str:
    shaped = _QUERY_VALUE.sub(r"\1<value>", line)
    shaped = _HTTP_STATUS.sub(
        lambda match: f'{match.group(1)} <http_{match.group(2)}xx>', shaped
    )
    for pattern, replacement in _NOISE:
        shaped = pattern.sub(replacement, shaped)
    return shaped.strip()[:MAX_LINE_CHARS]


def _line(line_no: int, line: str) -> dict[str, Any]:
    text = line.rstrip("\n")
    item: dict[str, Any] = {"line_no": line_no, "line": text[:MAX_LINE_CHARS]}
    if len(text) > MAX_LINE_CHARS:
        item.update({"clipped": True, "line_chars": len(text)})
    return item


def _stamp(nanos: str) -> str:
    try:
        return datetime.fromtimestamp(int(nanos) / 1e9, UTC).isoformat(
            timespec="seconds"
        )
    except (ValueError, OSError):
        return str(nanos)
