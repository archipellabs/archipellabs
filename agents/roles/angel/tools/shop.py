"""The shop as an API an analyst has to read, not as answers already computed.

This module used to have `carrier_coverage()` — one call that joined carriers,
zones and delivery rows and handed back "who ships where". Against a shipping
incident that *was* the answer, so a run measured whether the model could read a
table we had built for it. Nothing here now knows what a carrier is.

What is left is what a new analyst gets on their first day: a directory of
resources, the fields of each, and a way to make a read. Working out that "can we
ship to Canada" lives in `deliveries` joined to `zones` is the job, and it is the
part worth measuring.

Everything is a **read**. The identity holds a GET/HEAD-only Webservice key, so a
write is refused by PrestaShop with a 405 rather than by our own good manners, and
the key never appears in a tool signature — the agent knows it can call the shop,
not what opens it.
"""

import json
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from core.config import ShopConfig
from roles.angel.tools import bounded, data

MAX_ROWS = 25
"""How many rows a read returns before it is cut short.

Not a kindness. A bare `GET /orders` is hundreds of rows and would spend the
whole context on one call. What matters is that the cut is *declared* — see
`bounded.window`, which reports `complete` and `next_offset` so a partial answer
can never be read as the whole truth."""

MAX_ERROR_CHARS = 1200
"""How much of a refusal survives. Far more than a row gets, deliberately.

PrestaShop answers a bad query by naming the field that failed and listing every
field that would have worked — 970 characters of it for `carts`. Cut to the row
budget of 200 it lost 770, ending mid-list, and what reached the agent was
`HTTP 500` plus half a sentence. Two runs read that as a server fault and
reported it as the incident they had been sent to find. The actionable part of
an error IS the error, so it is not the place to save tokens."""


DATE_FIELDS = ("date_add", "date_upd", "invoice_date", "delivery_date")
"""Fields whose value is a shop-local timestamp with no zone attached.

Their presence is what triggers the timezone note below — the trap only bites
when a date is on the table, and a note on every response would be noise."""


def client(cfg: ShopConfig) -> httpx.AsyncClient:
    http = httpx.AsyncClient(
        base_url=cfg.base_url,
        # The key goes in the username; PrestaShop wants an empty password.
        auth=(cfg.api_key, ""),
        headers={"Output-Format": "JSON"},
        # The lab's certificate is self-signed.
        verify=False,
        timeout=30.0,
    )
    # Carried on the client so `get` can label timestamps without every caller
    # having to thread the config through.
    http.shop_timezone = cfg.timezone  # type: ignore[attr-defined]
    return http


async def resources(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Every resource this key can reach, with its description and verbs.

    The Webservice describes itself at its root, and only in XML — asking for
    JSON there returns an empty body. So this is the shop's own directory
    reformatted, not a list kept here that could drift away from it.
    """
    response = await http.get("/", headers={"Output-Format": "XML"})
    response.raise_for_status()
    api = ET.fromstring(response.text).find("api")
    if api is None:
        return []

    out: list[dict[str, Any]] = []
    for node in api:
        description = node.find("description")
        about = (description.text or "").strip() if description is not None else ""
        out.append(
            {
                "resource": node.tag,
                "about": about,
                "methods": sorted(
                    verb for verb in ("get", "head") if node.get(verb) == "true"
                ),
            }
        )
    return sorted(out, key=lambda r: str(r["resource"]))


async def schema(http: httpx.AsyncClient, resource: str) -> dict[str, Any]:
    """The fields of one resource, from the shop's own blank schema.

    XML again, for the same reason: `?schema=blank` in JSON answers `{"x": []}`,
    which says nothing. The field names are what make a `display=[...]` possible,
    and they are how a foreign key like `id_zone` becomes visible at all.
    """
    response = await http.get(
        f"/{resource}", params={"schema": "blank"}, headers={"Output-Format": "XML"}
    )
    if response.status_code >= 400:
        # 400, not 404, for a name that does not exist — and an unhandled raise
        # here would surface as a crash rather than as "try another name".
        return {
            "resource": resource,
            "error": f"no such resource (HTTP {response.status_code})",
        }

    entity = next(iter(ET.fromstring(response.text)), None)
    if entity is None:
        return {"resource": resource, "fields": []}
    return {
        "resource": resource,
        "entity": entity.tag,
        "fields": [field.tag for field in entity],
    }


def _wire(params: dict[str, Any]) -> dict[str, str]:
    """Turn ordinary JSON into the query string PrestaShop expects.

    Written after watching a run spend a third of its budget on this. Asked for
    five orders, a model sends `{"limit": 5, "display": ["id"]}` — the obvious
    encoding — and PrestaShop wants `limit=5` and `display=[id]`, brackets and
    all. Rejecting that as a type error taught it nothing except to guess at
    spellings, so the translation belongs here, once, rather than in the model's
    head on every call.
    """
    wire: dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, dict):
            # {"filter": {"iso_code": "CA"}} → filter[iso_code]=CA
            for inner, inner_value in value.items():
                wire[f"{key}[{inner}]"] = str(inner_value)
        elif isinstance(value, (list, tuple)):
            wire[key] = "[" + ",".join(str(item) for item in value) + "]"
        elif isinstance(value, bool):
            wire[key] = "1" if value else "0"
        else:
            wire[key] = str(value)
    return wire


def query_params(
    fields: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    sort: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Named arguments → the Webservice's query vocabulary.

    A flat, typed signature because that is the shape a model reaches for
    unprompted: traces show `{"limit": 1, "resource": "orders"}` sent flat while
    the schema demanded a nested `params` object, and an earlier `dict[str, str]`
    spent seven rejections and most of a request budget on encoding guesses. The
    nesting was never the shop's idea — it was ours.
    """
    params: dict[str, Any] = {}
    if fields:
        params["display"] = list(fields)
    if filters:
        params["filter"] = dict(filters)
        # PrestaShop ignores a date filter unless told the values are dates, and
        # ignoring it silently returns the unfiltered set — a wrong answer that
        # looks like a right one. Nobody should have to know this.
        if any(key in DATE_FIELDS for key in filters):
            params["date"] = 1
    if sort:
        params["sort"] = list(sort)
    if limit is not None:
        params["limit"] = f"{offset},{limit}" if offset else str(limit)
    elif offset:
        # **An offset with no limit used to be dropped in silence.** The shop's
        # only paging syntax is `limit=OFFSET,COUNT` — there is no way to say
        # "start at 100" alone — so a caller asking for `offset=100` and nothing
        # else produced no `limit` at all, and `_requested_window` reads the
        # offset back out of exactly that string. The read then began at row
        # zero and the envelope said `offset: 0`: honest about what it gave,
        # silent about ignoring what was asked. A caller following `next_offset`
        # without repeating `limit` re-read page one forever, and every page
        # agreed with the last.
        #
        # Given a count it can express the request, so it uses the page size the
        # answer is cut to anyway. `_requested_window` then sees a two-part
        # limit and reports `complete: "unknown"`, which is the truth: we asked
        # the server to withhold, and it does not say how much.
        params["limit"] = f"{offset},{MAX_ROWS}"
    return params


SORT_MAX_ROWS = 5000
"""How large a result may be before this tool declines to order it.

Ordering happens here, so the whole matching set has to arrive before any of it
can be ranked. That is nothing for this shop and would matter for a real one;
past the line, saying so beats quietly ranking a prefix."""


def _sort_terms(sort: list[Any]) -> tuple[list[tuple[str, bool]], str | None]:
    """`["date_add_DESC"]` → `[("date_add", True)]`, or why it cannot be read."""
    terms: list[tuple[str, bool]] = []
    for term in sort:
        field, _, direction = str(term).rpartition("_")
        if not field or direction.upper() not in {"ASC", "DESC"}:
            return [], (
                f"cannot read sort term {str(term)!r}; write FIELD_ASC or "
                f"FIELD_DESC, for example id_DESC or date_add_ASC"
            )
        terms.append((field, direction.upper() == "DESC"))
    return terms, None


def _order_key(value: Any) -> tuple[int, float, str]:
    """Order numbers as numbers, text as text, and blanks last — never raising.

    Shop columns mix the two: ids arrive as strings, so `"10"` sorts before
    `"9"` as text, and a column holding both a date and an empty string cannot be
    compared at all. Both are ordinary here, and a comparison that raises would
    turn a sort into a crash.
    """
    if value is None or value == "":
        return (2, 0.0, "")
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def _limit_parts(raw: Any) -> tuple[int, int | None]:
    """`"20,5"` → `(20, 5)`; `"5"` → `(0, 5)`; anything unreadable → `(0, None)`."""
    if raw is None:
        return 0, None
    head, _, tail = str(raw).partition(",")
    try:
        return (int(head), int(tail)) if tail else (0, int(head))
    except ValueError:
        return 0, None


def _refusal(resource: str, response: httpx.Response) -> dict[str, Any]:
    """A rejected query, in the shop's own words.

    PrestaShop says exactly what was wrong — *"Unable to display this field
    `associations`. However, these are available: id, id_address_delivery, …"* —
    and answers with a 500 while doing it. Reporting the status and a fragment of
    the body threw that away and left `HTTP 500`, which reads as a broken server
    rather than a fixable mistake.

    That is this toolset's recurring defect once more: a tool that cannot say *I
    did not understand you*. So the shop's message becomes the error, and the
    status becomes a detail.
    """

    def clip(message: str) -> str:
        """Never cut in silence — that is the defect this module keeps refinding."""
        if len(message) <= MAX_ERROR_CHARS:
            return message
        return (
            f"{message[:MAX_ERROR_CHARS]} …[cut here; {len(message)} characters "
            f"in full, so the list above is incomplete]"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None

    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        first = errors[0]
        message = str(first.get("message", "")).strip()
        if message:
            refusal: dict[str, Any] = {
                "resource": resource,
                "error": clip(message),
                "http": response.status_code,
            }
            if (code := first.get("code")) is not None:
                refusal["shop_code"] = code
            if len(errors) > 1:
                refusal["further_errors"] = [
                    clip(str(e.get("message", "")))
                    for e in errors[1:]
                    if isinstance(e, dict)
                ]
            return refusal

    return {
        "resource": resource,
        "error": f"HTTP {response.status_code}",
        "body": response.text[:MAX_ERROR_CHARS],
    }


def _requested_window(params: dict[str, Any] | None) -> tuple[int, bool]:
    """Where the caller's own `limit` starts, and whether it capped the result.

    PrestaShop takes `limit=N` or `limit=OFFSET,N`. When the caller set one, the
    shop decided what to withhold and we cannot tell whether more exist — that is
    the difference between reporting a count and reporting `unknown`.
    """
    raw = (params or {}).get("limit")
    if raw is None:
        return 0, False
    head, _, tail = str(raw).partition(",")
    if tail:
        try:
            return int(head), True
        except ValueError:
            return 0, True
    return 0, True


async def get(
    http: httpx.AsyncClient,
    resource: str,
    params: dict[str, Any] | None = None,
    into: str | None = None,
) -> dict[str, Any]:
    """One read against a resource, with whatever query parameters you pass.

    The Webservice's own vocabulary, because that is what the shop documents and
    what a person would type — but forgiving about the encoding, since a list and
    a number are the natural JSON for `display` and `limit`.

    **`sort` is honoured here, not by the shop.** Every encoding of it —
    `sort=[id_DESC]`, unbracketed, with the field displayed, with `date=1` —
    answers HTTP 200 and zero rows on the resources an investigation needs. The
    tool used to detect that and report it, which was honest and still a dead
    end: across ten graded runs a sort was refused 22 times and the run abandoned
    that resource 17 of them. "The most recent orders" is the first question
    anyone asks, so it has to work.
    """
    query = dict(params or {})
    order: list[tuple[str, bool]] = []
    caller_limit: Any = None
    if raw_sort := query.pop("sort", None):
        order, complaint = _sort_terms(list(raw_sort))
        if complaint:
            return {"resource": resource, "error": complaint}
        # The caller's limit cannot go to the shop either. Rows arrive
        # id-ascending, so limiting first and ordering second answers "the newest
        # of the oldest five" — a wrong answer wearing a right one's clothes,
        # which is the exact failure this module keeps being rewritten to avoid.
        # Fetch the matching set, order it, then take their slice.
        caller_limit = query.pop("limit", None)
        display = query.get("display")
        if isinstance(display, (list, tuple)):
            # You cannot order by a column you did not ask for: it comes back
            # absent, every key compares equal, and the result looks sorted.
            if absent := [f for f, _ in order if f not in display]:
                query["display"] = list(display) + absent

    response = await http.get(f"/{resource}", params=_wire(query))
    if response.status_code == 404:
        return {"resource": resource, "error": "no such resource"}
    if response.status_code >= 400:
        return _refusal(resource, response)

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {
            "resource": resource,
            "error": "not JSON",
            "body": response.text[:MAX_ERROR_CHARS],
        }

    # PrestaShop answers `{"orders": [...]}` on a hit and a bare `[]` on a miss,
    # so the shape changes with the result count. The empty case is the common
    # one, and unhandled it makes every "nothing found" look like a failure.
    rows = payload.get(resource, []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = [rows]

    sorted_by: dict[str, Any] | None = None
    matched: int | None = None
    if order:
        if len(rows) > SORT_MAX_ROWS:
            return {
                "resource": resource,
                "error": (
                    f"{len(rows)} rows match, past the {SORT_MAX_ROWS} this tool "
                    f"will order in memory; narrow it with a filter first"
                ),
            }
        if rows and (absent := [f for f, _ in order if not any(f in r for r in rows)]):
            return {
                "resource": resource,
                "error": f"cannot sort by {absent}: no row carries that field",
                "hint": "shop_schema names the fields this resource has",
            }
        # Applied right to left so the first term wins, which is what a reader of
        # `["country_ASC", "date_add_DESC"]` expects. Python's sort is stable, so
        # the later passes keep the earlier ordering inside each group.
        for field, descending in reversed(order):
            rows.sort(key=lambda row: _order_key(row.get(field)), reverse=descending)
        matched = len(rows)
        sort_offset, sort_count = _limit_parts(caller_limit)
        if sort_count is not None:
            rows = rows[sort_offset : sort_offset + sort_count]
        sorted_by = {"by": list(raw_sort), "over_rows": matched, "applied": "by me"}

    offset, server_capped = _requested_window(params)
    if matched is not None:
        offset, _ = _limit_parts(caller_limit)
        page_size = MAX_ROWS
    else:
        page_size = MAX_ROWS

    result: dict[str, Any] = {"resource": resource}
    if matched is not None:
        # We hold the whole matching set and did the slicing, so the count is
        # genuine and `complete` follows from it rather than being `unknown`.
        result.update(
            bounded.window(rows, cap=page_size, offset=offset, matched=matched)
        )
    else:
        result.update(
            bounded.window(
                rows, cap=page_size, offset=offset, server_capped=server_capped
            )
        )
    if sorted_by is not None:
        result["sorted"] = sorted_by

    if into is not None:
        # The completeness travels with the rows. Saved without it, a dataset
        # built from a capped read looked exactly like one built from a whole
        # table, and the next `aggregate` counted part of the truth and
        # presented the number as the answer.
        result["dataset"] = data.save(
            into, rows, complete=result.get("complete"), source=f"shop:{resource}"
        )

    dated = [
        (row, field)
        for row in result["rows"]
        for field in DATE_FIELDS
        if field in row
    ]
    if dated:
        # The span of what came back. A window reading 10:03–10:53 while the
        # clock says 15:53 is visible as stale at a glance; without it a run has
        # to infer staleness from ids, and two of them inferred wrongly.
        field = dated[0][1]
        stamps = sorted(str(row.get(field, "")) for row, _ in dated if row.get(field))
        if stamps:
            result["window"] = {"field": field, "first": stamps[0], "last": stamps[-1]}

        zone = getattr(http, "shop_timezone", "the shop's local zone")
        result["time_note"] = (
            f"timestamps above are {zone} local time, NOT UTC — log timestamps "
            f"are UTC, so do not compare the two without converting"
        )
    return result
