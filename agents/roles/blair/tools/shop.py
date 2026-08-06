"""Typed, bounded reads over the shop's own generic Webservice."""

import json
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from core.config import ShopConfig
from roles.blair.tools import bounded, tables

MAX_ROWS = 25
MAX_RESOURCES = 30
MAX_PREVIEW = 3
MAX_ERROR_CHARS = 1200
MAX_SORT_ROWS = 5000
DATE_FIELDS = ("date_add", "date_upd", "invoice_date", "delivery_date")


def client(cfg: ShopConfig) -> httpx.AsyncClient:
    http = httpx.AsyncClient(
        base_url=cfg.base_url,
        auth=(cfg.api_key, ""),
        headers={"Output-Format": "JSON"},
        verify=False,
        timeout=30.0,
    )
    http.shop_timezone = cfg.timezone  # type: ignore[attr-defined]
    return http


async def catalog(
    http: httpx.AsyncClient, search: str = "", offset: int = 0
) -> dict[str, Any]:
    """Resources exposed to this credential, from the API's own directory."""
    response = await http.get("/", headers={"Output-Format": "XML"})
    if response.status_code >= 400:
        return {"error": f"HTTP {response.status_code}"}
    try:
        api = ET.fromstring(response.text).find("api")
    except ET.ParseError as exc:
        return {"error": f"invalid directory XML: {exc}"}
    if api is None:
        return {"search": search, "resources": [], "total": 0, "complete": True}
    found: list[dict[str, Any]] = []
    for node in api:
        description = node.find("description")
        item = {
            "resource": node.tag,
            "about": (
                (description.text or "").strip()
                if description is not None
                else ""
            ),
            "methods": [
                verb for verb in ("get", "head") if node.get(verb) == "true"
            ],
        }
        haystack = f"{item['resource']} {item['about']}".casefold()
        if not search or search.casefold() in haystack:
            found.append(item)
    found.sort(key=lambda item: str(item["resource"]))
    offset = max(0, offset)
    result = {"search": search}
    result.update(
        bounded.page(
            found[offset:],
            limit=MAX_RESOURCES,
            offset=offset,
            total=len(found),
        )
    )
    result["resources"] = result.pop("rows")
    return result


async def describe(http: httpx.AsyncClient, resource: str) -> dict[str, Any]:
    response = await http.get(
        f"/{resource}",
        params={"schema": "blank"},
        headers={"Output-Format": "XML"},
    )
    if response.status_code >= 400:
        return {"resource": resource, "error": f"HTTP {response.status_code}"}
    try:
        entity = next(iter(ET.fromstring(response.text)), None)
    except ET.ParseError as exc:
        return {"resource": resource, "error": f"invalid schema XML: {exc}"}
    return {
        "resource": resource,
        "entity": entity.tag if entity is not None else None,
        "fields": [field.tag for field in entity] if entity is not None else [],
    }


def params(
    fields: list[str] | None,
    filters: dict[str, Any] | None,
    sort: list[str] | None,
    limit: int | None,
    offset: int,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if fields:
        query["display"] = list(fields)
    if filters:
        query["filter"] = dict(filters)
        if any(field in DATE_FIELDS for field in filters):
            query["date"] = 1
    if sort:
        query["sort"] = list(sort)
    if limit is not None:
        query["limit"] = f"{offset},{limit}" if offset else str(limit)
    return query


async def query(
    http: httpx.AsyncClient,
    resource: str,
    *,
    fields: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    sort: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
    save_as: str | None = None,
) -> dict[str, Any]:
    """Read rows, optionally saving them as a local table handle."""
    original = params(fields, filters, sort, limit, offset)
    remote = dict(original)
    order: list[tuple[str, bool]] = []
    if sort:
        order, error = _sort_terms(sort)
        if error:
            return {"resource": resource, "error": error}
        remote.pop("sort", None)
        remote.pop("limit", None)
        display = remote.get("display")
        if isinstance(display, list):
            for field, _ in order:
                if field not in display:
                    display.append(field)

    response = await http.get(f"/{resource}", params=_wire(remote))
    if response.status_code >= 400:
        return _refusal(resource, response)
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {
            "resource": resource,
            "error": "shop returned non-JSON",
            "body": response.text[:MAX_ERROR_CHARS],
        }
    rows = payload.get(resource, []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = [rows]
    rows = [row for row in rows if isinstance(row, dict)]

    matched: int | None = None
    source_complete: bounded.Completeness
    if order:
        if len(rows) > MAX_SORT_ROWS:
            return {
                "resource": resource,
                "error": f"{len(rows)} rows is too many to sort locally; filter first",
            }
        missing = [
            field
            for field, _ in order
            if rows and not any(field in row for row in rows)
        ]
        if missing:
            return {
                "resource": resource,
                "error": f"cannot sort: fields absent from rows: {missing}",
            }
        matched = len(rows)
        _sort_rows(rows, order)
        start = max(0, offset)
        end = start + limit if limit is not None else None
        rows = rows[start:end]
        source_complete = start == 0 and (limit is None or limit >= matched)

    caller_capped = limit is not None and not order
    if matched is not None:
        display_limit = min(MAX_ROWS, limit) if limit is not None else MAX_ROWS
        envelope = bounded.page(
            rows,
            limit=display_limit,
            offset=max(0, offset),
            total=matched,
        )
    elif caller_capped:
        source_complete = "unknown"
        envelope = bounded.page(
            rows,
            limit=MAX_ROWS,
            offset=max(0, offset),
            complete="unknown",
        )
    else:
        source_complete = True
        envelope = bounded.page(rows, limit=MAX_ROWS, total=len(rows))

    result: dict[str, Any] = {"resource": resource, **envelope}
    if order:
        result["sorted"] = {"by": sort, "over_rows": matched}
    _time_context(result, http)

    if save_as:
        receipt = tables.save(
            save_as,
            rows,
            source=f"shop:{resource}",
            complete=source_complete,
        )
        preview = result.pop("rows")[:MAX_PREVIEW]
        result["preview"] = preview
        result["table"] = receipt
    return result


def _wire(query: dict[str, Any]) -> dict[str, str]:
    wire: dict[str, str] = {}
    for key, value in query.items():
        if isinstance(value, dict):
            for field, wanted in value.items():
                wire[f"{key}[{field}]"] = str(wanted)
        elif isinstance(value, (list, tuple)):
            wire[key] = "[" + ",".join(str(item) for item in value) + "]"
        else:
            wire[key] = str(value)
    return wire


def _sort_terms(sort: list[str]) -> tuple[list[tuple[str, bool]], str | None]:
    terms: list[tuple[str, bool]] = []
    for raw in sort:
        field, _, direction = str(raw).rpartition("_")
        if not field or direction.upper() not in {"ASC", "DESC"}:
            return [], f"sort must use FIELD_ASC or FIELD_DESC, got {raw!r}"
        terms.append((field, direction.upper() == "DESC"))
    return terms, None


def _sort_rows(rows: list[dict[str, Any]], order: list[tuple[str, bool]]) -> None:
    for field, descending in reversed(order):
        present = [row for row in rows if row.get(field) not in (None, "")]
        blank = [row for row in rows if row.get(field) in (None, "")]
        present.sort(key=lambda row: _order_key(row.get(field)), reverse=descending)
        rows[:] = present + blank


def _order_key(value: Any) -> tuple[int, float, str]:
    try:
        return (1, float(value), "")
    except (TypeError, ValueError):
        return (0, 0.0, str(value))


def _refusal(resource: str, response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        message = str(errors[0].get("message", "")).strip()
        if message:
            return {
                "resource": resource,
                "error": _clip(message),
                "http": response.status_code,
            }
    return {
        "resource": resource,
        "error": f"HTTP {response.status_code}",
        "body": response.text[:MAX_ERROR_CHARS],
    }


def _clip(text: str) -> str:
    if len(text) <= MAX_ERROR_CHARS:
        return text
    return f"{text[:MAX_ERROR_CHARS]} …[truncated from {len(text)} chars]"


def _time_context(result: dict[str, Any], http: httpx.AsyncClient) -> None:
    dated = [
        (row, field)
        for row in result.get("rows", [])
        for field in DATE_FIELDS
        if row.get(field)
    ]
    if not dated:
        return
    field = dated[0][1]
    values = sorted(str(row[field]) for row, candidate in dated if candidate == field)
    result["time_window"] = {
        "field": field,
        "first": values[0],
        "last": values[-1],
        "timezone": getattr(http, "shop_timezone", "shop local time"),
    }
