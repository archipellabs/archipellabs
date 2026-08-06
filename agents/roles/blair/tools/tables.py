"""Generic table handles and relational operations.

Remote systems produce rows; analysis should not repeatedly paste those rows
into the model context.  This module stores them with provenance and exposes
only elementary operations: sample, filter, join, group, compare.  It knows
nothing about orders, markets, carriers, or the incident being tested.
"""

import json
import pathlib
import re
from typing import Any

from roles.blair.tools import bounded, workspace

MAX_SAMPLE = 20
MAX_GROUPS = 40
_MEASURE = re.compile(r"^(count|sum|avg|min|max)(?::(.+))?$")
_OPS = ("!=", ">=", "<=", "=", ">", "<", "~")


def _path(name: str) -> pathlib.Path | None:
    if name != pathlib.Path(name).name or not name or name.startswith("."):
        return None
    return workspace.tables() / f"{name}.json"


def save(
    name: str,
    rows: list[dict[str, Any]],
    *,
    source: str,
    complete: bounded.Completeness = True,
) -> dict[str, Any]:
    path = _path(name)
    if path is None:
        return {"table": name, "error": "table name must be one plain filename"}
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "rows": rows,
        "meta": {"source": source, "complete": complete},
    }
    path.write_text(json.dumps(payload, default=str))
    return describe(name)


def _read(name: str) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    path = _path(name)
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None
    meta = payload.get("meta")
    return payload["rows"], meta if isinstance(meta, dict) else {}


def load(name: str) -> list[dict[str, Any]] | None:
    found = _read(name)
    return found[0] if found else None


def describe(name: str) -> dict[str, Any]:
    found = _read(name)
    if found is None:
        return {"table": name, "error": "no such table"}
    rows, meta = found
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    return {
        "table": name,
        "row_count": len(rows),
        "fields": fields,
        "complete": meta.get("complete", "unknown"),
        "source": meta.get("source", "unknown"),
    }


def list_tables() -> list[dict[str, Any]]:
    root = workspace.tables()
    if not root.is_dir():
        return []
    return [describe(path.stem) for path in sorted(root.glob("*.json"))]


def sample(
    table: str,
    fields: list[str] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    found = _read(table)
    if found is None:
        return {"table": table, "error": "no such table"}
    rows, meta = found
    missing = _missing(rows, fields or [])
    if missing:
        return _field_error(table, missing)
    limit = max(1, min(limit, MAX_SAMPLE))
    offset = max(0, offset)
    selected = rows[offset : offset + limit]
    if fields:
        selected = [{field: row.get(field) for field in fields} for row in selected]
    result = {"table": table, "table_complete": meta.get("complete", "unknown")}
    result.update(bounded.page(selected, limit=limit, offset=offset, total=len(rows)))
    return result


def filter_rows(table: str, where: list[str], into: str) -> dict[str, Any]:
    found = _read(table)
    if found is None:
        return {"table": table, "error": "no such table"}
    rows, meta = found
    tests: list[tuple[str, str, str]] = []
    for clause in where:
        parsed = _parse_clause(clause)
        if parsed is None:
            return {
                "error": f"cannot read condition {clause!r}",
                "hint": "use field=value, !=, >, <, >=, <=, or field~text",
            }
        tests.append(parsed)
    missing = _missing(rows, [field for field, _, _ in tests])
    if missing:
        return _field_error(table, missing)
    kept = [row for row in rows if all(_matches(row, test) for test in tests)]
    receipt = save(
        into,
        kept,
        source=f"filter:{table}",
        complete=meta.get("complete", "unknown"),
    )
    receipt.update({"from_rows": len(rows), "removed": len(rows) - len(kept)})
    return receipt


def join(
    left: str,
    right: str,
    left_key: str,
    right_key: str,
    into: str,
    how: str = "inner",
) -> dict[str, Any]:
    a, b = _read(left), _read(right)
    if a is None or b is None:
        missing_table = left if a is None else right
        return {"error": f"no such table: {missing_table!r}"}
    left_rows, left_meta = a
    right_rows, right_meta = b
    if how not in {"inner", "left", "anti"}:
        return {"error": "how must be inner, left, or anti"}
    for name, rows, key in (
        (left, left_rows, left_key),
        (right, right_rows, right_key),
    ):
        if missing := _missing(rows, [key]):
            return _field_error(name, missing)

    index: dict[str, list[dict[str, Any]]] = {}
    for row in right_rows:
        value = row.get(right_key)
        if value not in (None, ""):
            index.setdefault(str(value), []).append(row)

    out: list[dict[str, Any]] = []
    matched_left = 0
    for row in left_rows:
        value = row.get(left_key)
        matches = index.get(str(value), []) if value not in (None, "") else []
        if not matches:
            if how in {"left", "anti"}:
                out.append(dict(row))
            continue
        matched_left += 1
        if how == "anti":
            continue
        for other in matches:
            combined = dict(row)
            for field, item in other.items():
                combined[f"right_{field}" if field in combined else field] = item
            out.append(combined)

    receipt = save(
        into,
        out,
        source=f"join:{left},{right}",
        complete=_combine_complete(
            left_meta.get("complete", "unknown"),
            right_meta.get("complete", "unknown"),
        ),
    )
    receipt.update(
        {
            "matched_left_rows": matched_left,
            "unmatched_left_rows": len(left_rows) - matched_left,
        }
    )
    return receipt


def group(
    table: str, group_by: list[str], measures: list[str] | None = None
) -> dict[str, Any]:
    rows, failure = _grouped(table, group_by, measures)
    if failure:
        return failure
    wanted = measures or ["count"]
    rows.sort(key=lambda row: _order(row.get(wanted[0])), reverse=True)
    return {
        "table": table,
        "groups": len(rows),
        "table_complete": describe(table).get("complete", "unknown"),
        **bounded.page(rows, limit=MAX_GROUPS, total=len(rows)),
    }


def compare(
    left: str,
    right: str,
    keys: list[str],
    measures: list[str] | None = None,
) -> dict[str, Any]:
    a, failure = _grouped(left, keys, measures)
    if failure:
        return failure
    b, failure = _grouped(right, keys, measures)
    if failure:
        return failure
    wanted = measures or ["count"]

    def indexed(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
        return {tuple(str(row.get(key, "")) for key in keys): row for row in rows}

    first, second = indexed(a), indexed(b)
    out: list[dict[str, Any]] = []
    for key in sorted(set(first) | set(second)):
        row: dict[str, Any] = dict(zip(keys, key, strict=True))
        row["in_left"], row["in_right"] = key in first, key in second
        for measure in wanted:
            before = first.get(key, {}).get(measure)
            after = second.get(key, {}).get(measure)
            row[f"left:{measure}"] = before
            row[f"right:{measure}"] = after
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                row[f"delta:{measure}"] = round(after - before, 3)
        out.append(row)

    def changed(row: dict[str, Any]) -> tuple[int, float]:
        one_side = row["in_left"] != row["in_right"]
        deltas = [
            abs(float(value))
            for field, value in row.items()
            if field.startswith("delta:") and isinstance(value, (int, float))
        ]
        magnitude = max(deltas, default=0.0)
        return (2 if one_side else int(magnitude > 0), magnitude)

    out.sort(key=changed, reverse=True)
    return {
        "left": left,
        "right": right,
        "groups": len(out),
        "left_complete": describe(left).get("complete", "unknown"),
        "right_complete": describe(right).get("complete", "unknown"),
        **bounded.page(out, limit=MAX_GROUPS, total=len(out)),
    }


def _grouped(
    table: str, group_by: list[str], measures: list[str] | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    found = _read(table)
    if found is None:
        return [], {"table": table, "error": "no such table"}
    rows, _ = found
    if missing := _missing(rows, group_by):
        return [], _field_error(table, missing)
    wanted = measures or ["count"]
    if invalid := [measure for measure in wanted if not _MEASURE.fullmatch(measure)]:
        return [], {
            "error": f"invalid measures: {invalid}",
            "hint": "use count, sum:field, avg:field, min:field, or max:field",
        }
    measure_fields = [
        match.group(2)
        for measure in wanted
        if (match := _MEASURE.fullmatch(measure)) and match.group(2)
    ]
    if missing := _missing(rows, measure_fields):
        return [], _field_error(table, missing)

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in group_by)
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for key, members in groups.items():
        item: dict[str, Any] = dict(zip(group_by, key, strict=True))
        for measure in wanted:
            item[measure] = _measure(members, measure)
        out.append(item)
    return out, None


def _measure(rows: list[dict[str, Any]], spec: str) -> Any:
    match = _MEASURE.fullmatch(spec)
    if match is None:
        return None
    kind, field = match.group(1), match.group(2)
    if kind == "count":
        return len(rows)
    values = [row.get(str(field)) for row in rows]
    values = [value for value in values if value not in (None, "")]
    numbers: list[float] = []
    for value in values:
        try:
            numbers.append(float(str(value)))
        except (TypeError, ValueError):
            pass
    if kind == "sum":
        return round(sum(numbers), 3)
    if kind == "avg":
        return round(sum(numbers) / len(numbers), 3) if numbers else None
    candidates: list[Any] = numbers if len(numbers) == len(values) else values
    if not candidates:
        return None
    return min(candidates, key=_order) if kind == "min" else max(candidates, key=_order)


def _parse_clause(clause: str) -> tuple[str, str, str] | None:
    for operator in _OPS:
        field, found, value = str(clause).partition(operator)
        if found and field.strip():
            return field.strip(), operator, value.strip()
    return None


def _matches(row: dict[str, Any], test: tuple[str, str, str]) -> bool:
    field, operator, wanted = test
    raw = row.get(field)
    actual = "" if raw is None else str(raw)
    if operator == "~":
        return wanted.casefold() in actual.casefold()
    if operator == "=":
        return actual == wanted
    if operator == "!=":
        return actual != wanted
    try:
        left: Any = float(actual)
        right: Any = float(wanted)
    except ValueError:
        left, right = actual, wanted
    # `bool(...)` because the comparands are `Any`: a custom `__gt__` may return
    # anything at all, and this function promises a bool to every caller.
    return bool(
        {
            ">": left > right,
            "<": left < right,
            ">=": left >= right,
            "<=": left <= right,
        }[operator]
    )


def _missing(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    return [field for field in fields if rows and not any(field in row for row in rows)]


def _field_error(table: str, missing: list[str]) -> dict[str, Any]:
    return {
        "table": table,
        "error": f"unknown fields: {missing}",
        "fields": describe(table).get("fields", []),
    }


def _combine_complete(left: Any, right: Any) -> bounded.Completeness:
    if False in (left, right):
        return False
    if left is True and right is True:
        return True
    return "unknown"


def _order(value: Any) -> tuple[int, float, str]:
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (2, float(value), "")
    try:
        return (2, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))
