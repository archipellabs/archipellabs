"""Join, group and compare — the mechanical half of an analysis.

A tool should remove mechanical work, not make the business inference. Counting
orders per country is mechanical: it needs three resources, three schemas, paging
and a two-hop join, and every run so far spent a large share of its budget doing
it by hand — one used 22 shop calls to assemble what a dashboard answers in one.
Deciding that a missing Canadian carrier explains the drop is *not* mechanical,
and nothing here does it.

So there is no `carrier_coverage()`. There is `join`, `aggregate` and `compare`,
which know nothing about shops.

**Datasets live on disk.** An investigation needs seven hundred orders to count
them and needs none of them in its context. A handle carries the shape — how many
rows, which fields — while the rows stay in a file, the same bargain the log
tools already make.
"""

import json
import os
import pathlib
import re
from typing import Any

from roles.angel.tools import bounded, workspace

DATA_DIR = pathlib.Path(
    os.getenv("AGENT_DATA_DIR")
    or pathlib.Path(__file__).resolve().parents[1] / "datasets"
)
"""Where datasets live when no investigation is running."""


def _root() -> pathlib.Path:
    """This run's dataset directory, or the shared one outside a run.

    Per run, because the shared folder let an investigation list the datasets the
    previous one had built — and a name like `complaint_carts` is a hypothesis,
    not data. See `workspace`.
    """
    return workspace.datasets() or DATA_DIR


MAX_GROUPS = 50
"""Groups returned by an aggregate. A group-by that explodes is a mistake worth
seeing rather than a wall of rows: the count is reported either way."""

MEASURE = re.compile(r"^(count|sum|avg|min|max)(?::(.+))?$")


def _path(name: str) -> pathlib.Path | None:
    """A dataset inside this run's directory, or nothing. Never escapes it."""
    safe = pathlib.Path(name).name
    if not safe or safe.startswith("."):
        return None
    return _root() / f"{safe}.json"


def save(
    name: str,
    rows: list[dict[str, Any]],
    *,
    complete: bool | str | None = None,
    source: str = "",
) -> dict[str, Any]:
    """Write rows to a named dataset, and what is known about their completeness.

    **A dataset built from a capped read used to arrive here stripped of that
    fact.** The read itself reports `complete: "unknown"`, honestly; then the
    rows were saved, and the marker was not. An `aggregate` over that dataset
    counted a partial set and answered as though it were the whole — which is
    this package's founding lie, one layer further along than the layer written
    to retire it. A count is only a count of what was actually fetched.

    `complete` is `True`, `False` or `"unknown"`, in `bounded.window`'s
    vocabulary, and absent when the caller genuinely does not say — a dataset
    the model assembled itself, for instance.
    """
    path = _path(name)
    if path is None:
        return {"error": f"{name!r} is not a usable dataset name"}
    _root().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, default=str))
    meta = _meta_path(name)
    if meta is not None:
        if complete is None and not source:
            meta.unlink(missing_ok=True)
        else:
            meta.write_text(json.dumps({"complete": complete, "source": source}))
    return info(name)


def _meta_path(name: str) -> pathlib.Path | None:
    path = _path(name)
    return None if path is None else path.with_suffix(".meta.json")


def load(name: str) -> list[dict[str, Any]] | None:
    path = _path(name)
    if path is None or not path.is_file():
        return None
    parsed = json.loads(path.read_text())
    return parsed if isinstance(parsed, list) else None


def info(name: str) -> dict[str, Any]:
    """The shape of a dataset — never its contents.

    Reports the name actually used, not the one asked for. A handle that echoed
    back `/etc/passwd` after safely writing `passwd.json` would be a truthful
    file and a lying receipt, and the next call would be made against a name that
    does not mean what the caller thinks.
    """
    rows = load(name)
    path = _path(name)
    if rows is None or path is None:
        return {"dataset": name, "error": "no such dataset"}
    name = path.stem
    fields: list[str] = []
    for row in rows[:200]:
        for key in row:
            if key not in fields:
                fields.append(key)
    handle: dict[str, Any] = {
        "dataset": name,
        "rows": len(rows),
        "fields": fields,
    }
    # Carried on the handle, because the handle is what a caller reads before
    # deciding whether a count over these rows means anything. A dataset built
    # from a capped read holds part of the truth, and `rows` alone says only how
    # much of it happens to be here.
    handle.update(_provenance(name))
    return handle


def _provenance(name: str) -> dict[str, Any]:
    """What is known about where a dataset came from, and how much of it."""
    meta = _meta_path(name)
    if meta is None or not meta.is_file():
        return {}
    known = json.loads(meta.read_text())
    return {key: value for key, value in known.items() if value not in (None, "")}


def datasets() -> list[dict[str, Any]]:
    """The datasets built during this investigation."""
    if not _root().is_dir():
        return []
    return [
        info(path.stem)
        for path in sorted(_root().glob("*.json"))
        if not path.name.endswith(".meta.json")
    ]


def join(
    left: str,
    right: str,
    left_key: str,
    right_key: str,
    into: str,
    how: str = "inner",
) -> dict[str, Any]:
    """Match rows of two datasets on a key.

    `how="left"` keeps unmatched left rows with the right fields absent, and
    `how="anti"` keeps *only* those — "carts that never became an order" is the
    shape half of these questions take, and asking for it directly beats a left
    join the caller then has to filter by hand.

    A right field whose name collides is prefixed `r_`, so a join never silently
    overwrites the column someone is about to group by.

    **A key that no row carries is refused, and a row that carries none matches
    nothing.** Those are two halves of one bug and only the first was fixed.
    A join between two misspelled columns reported every row matched and
    nothing unmatched — confident, complete, entirely false — because missing
    keys read as `None` on both sides and `None` equalled `None`. Refusing an
    absent *field* closed that. It left the ordinary case open: a field that
    exists and is null on some rows still paired every such row with every
    other, which in this shop means every address-less cart against every
    carrier-less order.
    """
    left_rows, right_rows = load(left), load(right)
    if left_rows is None:
        return {"error": f"no such dataset: {left!r}"}
    if right_rows is None:
        return {"error": f"no such dataset: {right!r}"}
    if how not in {"inner", "left", "anti"}:
        return {"error": f"how must be 'inner', 'left' or 'anti', got {how!r}"}
    for name, rows, key in (
        (left, left_rows, left_key),
        (right, right_rows, right_key),
    ):
        if rows and not any(key in row for row in rows):
            return {
                "error": f"{name!r} has no field {key!r}",
                "fields": info(name).get("fields", []),
            }

    # **A missing key matches nothing, not everything.** The key used to be
    # `str(row.get(...))`, which turns an absent or null value into the string
    # `"None"` — on both sides. Every left row without the key then joined to
    # every right row without it: a cross product of exactly the rows that carry
    # no information, silently inflating the result and inventing pairs. A cart
    # with no delivery address and an order with no carrier are ordinary in this
    # shop, and joining them would manufacture precisely the kind of correlation
    # an investigation is here to find. SQL refuses to equate two NULLs for the
    # same reason.
    index: dict[str, list[dict[str, Any]]] = {}
    for row in right_rows:
        joins_on = _join_key(row, right_key)
        if joins_on is not None:
            index.setdefault(joins_on, []).append(row)

    merged: list[dict[str, Any]] = []
    unmatched = 0
    for row in left_rows:
        joins_on = _join_key(row, left_key)
        matches = index.get(joins_on, []) if joins_on is not None else []
        if not matches:
            unmatched += 1
            if how in {"left", "anti"}:
                merged.append(dict(row))
            continue
        if how == "anti":
            continue
        for match in matches:
            combined = dict(row)
            for key, value in match.items():
                combined[f"r_{key}" if key in row else key] = value
            merged.append(combined)

    result = save(into, merged)
    result["matched_left_rows"] = len(left_rows) - unmatched
    result["unmatched_left_rows"] = unmatched
    return result


def _join_key(row: dict[str, Any], field: str) -> str | None:
    """One row's join key, or `None` when it has none to offer.

    Empty string counts as absent too: PrestaShop returns `""` for an unset
    integer reference as often as it returns nothing at all, and treating the
    two differently would make a join's result depend on which of them the API
    happened to send.
    """
    value = row.get(field)
    if value is None or value == "":
        return None
    return str(value)


COMPARISONS = ("!=", ">=", "<=", "=", ">", "<", "~")
"""Longest first: `>=` must be tried before `>`, or `n>=5` parses as `n > "=5"`."""


def filter_(dataset: str, where: list[str], into: str) -> dict[str, Any]:
    """Keep the rows matching every condition, as a new dataset.

    Conditions are `field=value`, `!=`, `>`, `<`, `>=`, `<=`, or `field~text`
    for "contains". Numbers compare as numbers when both sides look numeric.

    Together with `join(how="anti")` this is what makes a question like "carts
    with a Canadian address that never became an order" answerable out of
    primitives — which is the alternative to shipping a `shop_abandoned_carts()`
    that would answer the incident on the agent's behalf.
    """
    rows = load(dataset)
    if rows is None:
        return {"dataset": dataset, "error": "no such dataset"}

    tests: list[tuple[str, str, str]] = []
    for clause in where:
        for symbol in COMPARISONS:
            field, found, value = str(clause).partition(symbol)
            if found and field:
                tests.append((field.strip(), symbol, value.strip()))
                break
        else:
            return {
                "error": f"cannot read condition {clause!r}",
                "hint": "write field=value, or != > < >= <= , or field~text",
            }

    unknown = [f for f, _, _ in tests if rows and not any(f in row for row in rows)]
    if unknown:
        return {
            "error": f"{dataset!r} has no field(s) {unknown}",
            "fields": info(dataset).get("fields", []),
        }

    kept = [row for row in rows if all(_matches(row, t) for t in tests)]
    result = save(into, kept)
    result["from_rows"] = len(rows)
    result["removed"] = len(rows) - len(kept)
    return result


def _matches(row: dict[str, Any], test: tuple[str, str, str]) -> bool:
    field, symbol, wanted = test
    raw = row.get(field)
    actual = "" if raw is None else str(raw)
    if symbol == "~":
        return wanted.lower() in actual.lower()
    if symbol == "=":
        return actual == wanted
    if symbol == "!=":
        return actual != wanted
    try:
        left, right = float(actual), float(wanted)
    except (TypeError, ValueError):
        left_text, right_text = actual, wanted
        return {
            ">": left_text > right_text,
            "<": left_text < right_text,
            ">=": left_text >= right_text,
            "<=": left_text <= right_text,
        }[symbol]
    return {
        ">": left > right,
        "<": left < right,
        ">=": left >= right,
        "<=": left <= right,
    }[symbol]


def sample(
    dataset: str,
    fields: list[str] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Look at some actual rows — the shape of a dataset is not its contents.

    Everything else here reports counts and handles. Eventually someone has to
    read a row to know whether `id_carrier` is `0` or empty, and doing that by
    aggregating on a hunch costs more calls than looking.
    """
    rows = load(dataset)
    if rows is None:
        return {"dataset": dataset, "error": "no such dataset"}
    window = rows[offset : offset + limit]
    if fields:
        window = [{f: row.get(f) for f in fields if f in row} for row in window]
    return {
        "dataset": dataset,
        **bounded.window(window, cap=limit, offset=offset, matched=len(rows)),
    }


def _measure(rows: list[dict[str, Any]], spec: str) -> tuple[str, Any] | None:
    """One measure over a group. Unparseable specs are reported, not guessed."""
    match = MEASURE.match(spec.strip())
    if match is None:
        return None
    kind, field = match.group(1), match.group(2)
    if kind == "count":
        return spec, len(rows)
    if field is None:
        return None

    values = []
    for row in rows:
        raw = row.get(field)
        if raw is None or raw == "":
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            if kind in {"min", "max"}:
                values.append(raw)  # dates and ids order fine as strings
    if not values:
        return spec, None
    if kind == "sum":
        return spec, round(sum(v for v in values if isinstance(v, float)), 2)
    if kind == "avg":
        numbers = [v for v in values if isinstance(v, float)]
        return spec, round(sum(numbers) / len(numbers), 2) if numbers else None
    return spec, min(values, key=_ordering) if kind == "min" else max(
        values, key=_ordering
    )


def _ordering(value: Any) -> tuple[int, float, str]:
    """Numbers against numbers, text against text — never one against the other.

    This used to be `key=_ordering`, which made every comparison lexicographic. It was
    there to stop a mixed column raising `TypeError`, and it did — by making the
    answer wrong instead: `min` over `[10, 2]` compared `"10.0"` against `"2.0"`
    and returned **10**. An analyst asking for the lowest stock level got the
    highest, silently, whenever the two numbers had different digit counts.

    A column is mixed only when some of its values would not parse. Numbers sort
    first among themselves, text after among itself, so the order is total and
    type-correct, and an ISO date — the case the string fallback exists for —
    still orders exactly as it reads.
    """
    if isinstance(value, float):
        return (0, value, "")
    return (1, 0.0, str(value))


def _grouped(
    dataset: str, group_by: list[str], measures: list[str] | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Every group, untruncated — the display cap belongs to the caller.

    `compare` used to read `aggregate`'s already-capped rows, so a group past the
    fiftieth was reported as absent from one side rather than merely unshown.
    "This market stopped appearing" is the headline `compare` exists to produce,
    and it was manufacturing it.
    """
    rows = load(dataset)
    if rows is None:
        return [], {"dataset": dataset, "error": "no such dataset"}
    wanted = measures or ["count"]
    unknown = [m for m in wanted if MEASURE.match(m.strip()) is None]
    if unknown:
        return [], {
            "error": f"unusable measure(s): {unknown}",
            "hint": "use count, or sum:field / avg:field / min:field / max:field",
        }
    missing = [f for f in group_by if rows and not any(f in row for row in rows)]
    if missing:
        return [], {
            "error": f"{dataset!r} has no field(s) {missing}",
            "fields": info(dataset).get("fields", []),
        }

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in group_by)
        groups.setdefault(key, []).append(row)

    out: list[dict[str, Any]] = []
    for key, members in groups.items():
        entry: dict[str, Any] = dict(zip(group_by, key, strict=True))
        for spec in wanted:
            measured = _measure(members, spec)
            if measured is not None:
                entry[measured[0]] = measured[1]
        out.append(entry)

    # Numbers as numbers. Sorting the leading measure as text put 9 above 100,
    # so "the biggest groups" were whichever ones started with a high digit.
    out.sort(key=lambda e: _order(e.get(wanted[0])), reverse=True)
    return out, None


def _order(value: Any) -> tuple[int, float, str]:
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (2, float(value), "")
    try:
        return (2, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def aggregate(
    dataset: str, group_by: list[str], measures: list[str] | None = None
) -> dict[str, Any]:
    """Group rows and measure each group.

    Measures are `count`, or `sum:field` / `avg:field` / `min:field` /
    `max:field`. An empty `group_by` measures the whole dataset, which is how a
    total is asked for.
    """
    out, failure = _grouped(dataset, group_by, measures)
    if failure is not None:
        return failure
    result: dict[str, Any] = {"dataset": dataset, "groups": len(out)}
    if len(out) > MAX_GROUPS:
        result["rows"] = out[:MAX_GROUPS]
        result["note"] = f"showing {MAX_GROUPS} of {len(out)} groups"
    else:
        result["rows"] = out
    return result


def compare(
    left: str, right: str, keys: list[str], measures: list[str] | None = None
) -> dict[str, Any]:
    """The same aggregate over two datasets, side by side, with the delta.

    "What changed between these two windows" is the question an incident actually
    asks, and answering it by reading two tables and subtracting in your head is
    where a run loses the thread. Rows present on one side only are marked, since
    a market that stopped appearing at all is the interesting case.

    Compares **every** group, not the fifty each side would display. Reading the
    capped rows made "absent from the right" and "fifty-first on the right" the
    same answer, and the first of those is precisely the finding this returns.
    """
    first, failure = _grouped(left, keys, measures)
    if failure is not None:
        return failure
    second, failure = _grouped(right, keys, measures)
    if failure is not None:
        return failure

    wanted = measures or ["count"]

    def index(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
        return {tuple(str(r.get(k, "")) for k in keys): r for r in rows}

    a, b = index(first), index(second)
    out: list[dict[str, Any]] = []
    for key in sorted(set(a) | set(b)):
        entry: dict[str, Any] = dict(zip(keys, key, strict=True))
        entry["in_left"], entry["in_right"] = key in a, key in b
        for spec in wanted:
            lv, rv = a.get(key, {}).get(spec), b.get(key, {}).get(spec)
            entry[f"left:{spec}"], entry[f"right:{spec}"] = lv, rv
            if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
                entry[f"delta:{spec}"] = round(rv - lv, 2)
        out.append(entry)

    result: dict[str, Any] = {
        "left": left,
        "right": right,
        "keys": keys,
        "groups": len(out),
    }
    if len(out) > MAX_GROUPS:
        # Compared in full; only the display is cut, and it says so.
        result["rows"] = out[:MAX_GROUPS]
        result["note"] = f"showing {MAX_GROUPS} of {len(out)} compared groups"
    else:
        result["rows"] = out
    return result
