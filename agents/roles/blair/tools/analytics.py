"""Discover and call Matomo reports without preselecting a business question."""

from typing import Any

import httpx

from core.config import MatomoConfig
from roles.blair.tools import bounded, tables

MAX_REPORTS = 30
MAX_ROWS = 25
MAX_PREVIEW = 3


def client(cfg: MatomoConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=cfg.base_url, verify=False, timeout=30.0)


async def _call(
    http: httpx.AsyncClient, cfg: MatomoConfig, method: str, **params: str
) -> Any:
    response = await http.post(
        "/index.php",
        params={
            "module": "API",
            "method": method,
            "idSite": cfg.site_id,
            "format": "JSON",
            **params,
        },
        data={"token_auth": cfg.token},
    )
    if response.status_code >= 400:
        return {"error": f"HTTP {response.status_code}", "body": response.text[:300]}
    try:
        payload = response.json()
    except ValueError:
        return {"error": "analytics returned non-JSON", "body": response.text[:300]}
    if isinstance(payload, dict) and payload.get("result") == "error":
        return {"error": str(payload.get("message", "analytics refused the call"))}
    return payload


async def catalog(
    http: httpx.AsyncClient,
    cfg: MatomoConfig,
    search: str = "",
    offset: int = 0,
) -> dict[str, Any]:
    """Search Matomo's own report directory, without a hard-coded report list."""
    payload = await _call(http, cfg, "API.getReportMetadata")
    if isinstance(payload, dict) and "error" in payload:
        return payload
    if not isinstance(payload, list):
        return {"error": "analytics report directory has an unexpected shape"}
    reports: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        metrics = raw.get("metrics")
        report = {
            "method": f"{raw.get('module')}.{raw.get('action')}",
            "name": raw.get("name"),
            "category": raw.get("category"),
            "dimension": raw.get("dimension"),
            "metrics": sorted(metrics) if isinstance(metrics, dict) else [],
        }
        haystack = " ".join(str(value) for value in report.values()).casefold()
        if not search or search.casefold() in haystack:
            reports.append(report)
    reports.sort(key=lambda report: str(report["method"]))
    offset = max(0, offset)
    result = {"search": search}
    result.update(
        bounded.page(
            reports[offset:],
            limit=MAX_REPORTS,
            offset=offset,
            total=len(reports),
        )
    )
    result["reports"] = result.pop("rows")
    return result


async def query(
    http: httpx.AsyncClient,
    cfg: MatomoConfig,
    method: str,
    params: dict[str, Any] | None = None,
    save_as: str | None = None,
) -> dict[str, Any]:
    """Call one discovered report and preserve its native rows-or-metrics shape."""
    asked = params or {}
    payload = await _call(http, cfg, method, **{k: str(v) for k, v in asked.items()})
    if isinstance(payload, dict) and "error" in payload:
        return {"method": method, **payload}
    if not isinstance(payload, list):
        return {"method": method, "shape": "metrics", "data": payload}

    offset = max(0, int(str(asked.get("filter_offset", 0)) or 0))
    raw_limit = asked.get("filter_limit")
    if str(raw_limit) == "-1":
        source_complete: bounded.Completeness = offset == 0
        total = offset + len(payload)
        envelope = bounded.page(
            payload,
            limit=MAX_ROWS,
            offset=offset,
            total=total,
        )
    else:
        source_complete = "unknown"
        envelope = bounded.page(
            payload,
            limit=MAX_ROWS,
            offset=offset,
            complete=source_complete,
        )

    result: dict[str, Any] = {"method": method, "shape": "rows", **envelope}
    if save_as:
        receipt = tables.save(
            save_as,
            payload,
            source=f"analytics:{method}",
            complete=source_complete,
        )
        result["preview"] = result.pop("rows")[:MAX_PREVIEW]
        result["table"] = receipt
    return result
