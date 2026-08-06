"""Matomo as an API an analyst has to read, not as one report already chosen.

This module used to expose `visits_by_country()` — one call that picked the
report, fixed the period, and renamed the fields. It was the traffic-shaped twin
of the carrier tool that used to hand over the shipping answer, and every run so
far quoted conversion rates it had not computed. Nothing here now knows what a
country is.

What is left mirrors the shop: a directory of what can be asked, and a way to
ask it. Matomo publishes its own catalogue through `API.getReportMetadata`, so
the directory is Matomo's rather than a list kept here that could drift.

The business half of the evidence. Matomo knows visitors arrived and where from;
it does not know whether they bought, which is exactly the gap that makes an
incident visible as a *divergence* between two systems rather than an error in
either.
"""

from typing import Any

import httpx

from core.config import MatomoConfig
from roles.dana.tools import bounded

MAX_ROWS = 25
"""Rows returned before a report is cut short.

Matomo pages natively with `filter_limit`/`filter_offset`, which map onto the
`next_offset` this returns. Note that a report the caller limited comes back
`complete: "unknown"` — Matomo applies its own server-side default and does not
say what it withheld, so any count we reported would be invented."""


def client(cfg: MatomoConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=cfg.base_url, verify=False, timeout=30.0)


async def _call(
    http: httpx.AsyncClient, cfg: MatomoConfig, method: str, **params: str
) -> Any:
    """One Matomo API call. Returns the payload, or an error dict — never raises.

    Matomo answers a bad request with **HTTP 200** and
    `{"result": "error", "message": ...}`. Handing that back as data is the same
    trap PrestaShop's silent empty sort set, and it cost a run a fabricated root
    cause: a tool that cannot say "I did not understand you" invites the model to
    explain the nonsense instead. Its messages are unusually good — they list the
    accepted values — so they are passed through verbatim.
    """
    # token_auth must be POSTed: Matomo 5 refuses a token in the query string.
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
        return {
            "error": f"HTTP {response.status_code}",
            "hint": "check the method name against analytics_reports",
            "body": response.text[:200],
        }
    try:
        payload = response.json()
    except ValueError:
        return {"error": "not JSON", "body": response.text[:200]}

    if isinstance(payload, dict) and payload.get("result") == "error":
        return {"error": payload.get("message", "Matomo refused the call")}
    return payload


async def reports(
    http: httpx.AsyncClient,
    cfg: MatomoConfig,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Every report this site can answer, from Matomo's own catalogue.

    `method` is what `analytics_get` takes; `dimension` is what the rows are
    broken down by, which is the part that decides whether a report can answer
    "who is affected".
    """
    data = await _call(http, cfg, "API.getReportMetadata")
    if isinstance(data, dict) and "error" in data:
        return data
    if not isinstance(data, list):
        return []

    out: list[dict[str, Any]] = []
    for report in data:
        metrics = report.get("metrics") or {}
        out.append(
            {
                "method": f"{report.get('module')}.{report.get('action')}",
                "name": report.get("name"),
                "category": report.get("category"),
                "dimension": report.get("dimension"),
                "metrics": sorted(metrics) if isinstance(metrics, dict) else [],
            }
        )
    return sorted(out, key=lambda r: str(r["method"]))


async def get(
    http: httpx.AsyncClient,
    cfg: MatomoConfig,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one Matomo API method and report what came back.

    The shape varies by report — a list of rows, a single dict of metrics, or a
    dict keyed by date for a multi-period request — so the envelope says which,
    rather than forcing everything into a list and losing the distinction.
    """
    data = await _call(
        http, cfg, method, **{k: str(v) for k, v in (params or {}).items()}
    )
    if isinstance(data, dict) and "error" in data:
        return {"method": method, **data}

    if isinstance(data, list):
        asked = params or {}
        offset = int(str(asked.get("filter_offset", 0)) or 0)
        raw_limit = asked.get("filter_limit")
        server_capped = raw_limit is not None and str(raw_limit) != "-1"
        result: dict[str, Any] = {"method": method, "shape": "rows"}
        result.update(
            bounded.window(
                data,
                cap=MAX_ROWS,
                offset=offset,
                server_capped=server_capped,
            )
        )
        return result

    return {"method": method, "shape": "metrics", "data": data}
