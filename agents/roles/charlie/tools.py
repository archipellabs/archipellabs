"""Charlie's reads of the company. Plain functions; the MCP layer is elsewhere.

Same systems Angel reaches — the shop's Webservice, Loki, the ERP feed — and the
same rule: a tool removes mechanical work, it does not make the business
inference. Nothing here knows what a carrier is.

**These are deliberately thinner than Angel's** — no joins, no aggregation, no
client-side sort. That thinness is Charlie's variable, paired against Dana, which
runs the same loop over Angel's rich readers.

**Completeness is not part of it.** These readers carry `bounded.window` because
a page that does not say it is a page is not a thinner answer, it is a wrong one:
a saturated read of 25 rows read exactly like an exhausted one, and on the
scenario whose answer is an exact population count Charlie scored 2 of 18 while
Angel, whose reader reports that figure, got it on its first or second call in 14
of 15 transcripts. That gap was this file, not the harness. What stays genuinely
thin — and is still the experiment — is the client-side sort and the translated
Webservice refusals.
"""

import json
import re
from typing import Any

import httpx

from core.config import Config
from roles.charlie import bounded

MAX_ROWS = 25
MAX_MATCHES = 40
MAX_LINE_CHARS = 300
MAX_FEED_CHARS = 20_000


def _shop(cfg: Config) -> httpx.Client:
    return httpx.Client(
        base_url=cfg.shop.base_url,
        auth=(cfg.shop.api_key, ""),
        headers={"Output-Format": "JSON"},
        verify=False,
        timeout=30.0,
    )


def shop_resources(cfg: Config) -> dict[str, Any]:
    """Every resource this key can reach. The Webservice describes itself in XML."""
    with _shop(cfg) as http:
        response = http.get("/", headers={"Output-Format": "XML"})
    names = re.findall(r"<(\w+)\s+[^>]*get=\"true\"", response.text)
    return {"resources": sorted(set(names))}


def shop_schema(cfg: Config, resource: str) -> dict[str, Any]:
    """The fields of one resource, from the shop's own blank schema."""
    with _shop(cfg) as http:
        response = http.get(
            f"/{resource}",
            params={"schema": "blank"},
            headers={"Output-Format": "XML"},
        )
    if response.status_code >= 400:
        return {
            "resource": resource,
            "error": f"no such resource (HTTP {response.status_code})",
        }
    fields = re.findall(r"<(\w+)\s*/?>", response.text)
    return {"resource": resource, "fields": [f for f in dict.fromkeys(fields)][2:]}


def shop_get(
    cfg: Config,
    resource: str,
    fields: list[str] | None = None,
    filters: dict[str, str] | None = None,
    limit: int = MAX_ROWS,
    offset: int = 0,
) -> dict[str, Any]:
    """One read against a resource, in the Webservice's own query vocabulary.

    `offset` exists because the envelope below reports `next_offset`, and an
    answer that tells the caller where to continue while offering no way to get
    there would be a fresh version of the defect it was added to fix. It is a
    paging primitive, not an analysis one: this tool still joins nothing and
    aggregates nothing.
    """
    # `limit=offset,count` is the Webservice's own paging syntax, and the plain
    # form is not the same request — sending `limit=25` from offset 100 quietly
    # returns the first 25 rows again.
    params: dict[str, str] = {"limit": f"{offset},{limit}" if offset else str(limit)}
    if fields:
        params["display"] = "[" + ",".join(fields) + "]"
    for key, value in (filters or {}).items():
        params[f"filter[{key}]"] = str(value)
        if key.startswith("date_"):
            # PrestaShop ignores a date filter unless told the values are dates,
            # and ignoring it silently returns the unfiltered set.
            params["date"] = "1"

    with _shop(cfg) as http:
        response = http.get(f"/{resource}", params=params)
    if response.status_code >= 400:
        return {
            "resource": resource,
            "error": f"HTTP {response.status_code}",
            "body": response.text[:1200],
        }
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {"resource": resource, "error": "not JSON", "body": response.text[:600]}

    rows = payload.get(resource, []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = [rows]
    # `server_capped` is always true here: this tool never asks the shop for an
    # unbounded set. When the caller raises `limit` past MAX_ROWS the first
    # branch of `window` takes over and the count becomes genuine, which is the
    # route to a figure like 214 that this tool used to make unreachable.
    return {
        "resource": resource,
        **bounded.window(rows, cap=MAX_ROWS, offset=offset, server_capped=True),
    }


def logs_query(
    cfg: Config, service: str, pattern: str, minutes: int = 30
) -> dict[str, Any]:
    """Search one service's recent log. Returns counted, clipped matches."""
    with httpx.Client(base_url=cfg.loki.base_url, timeout=60.0) as http:
        response = http.get(
            "/loki/api/v1/query_range",
            params={
                "query": f'{{service="{service}"}}',
                "limit": "5000",
                "since": f"{minutes}m",
            },
        )
    if response.status_code >= 400:
        return {"service": service, "error": f"HTTP {response.status_code}"}

    lines: list[str] = []
    for stream in response.json().get("data", {}).get("result", []):
        for _stamp, line in stream.get("values", []):
            lines.append(line.rstrip("\n"))
    lines.reverse()

    try:
        needle = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return {"service": service, "error": f"bad pattern: {exc}"}

    hits = [line[:MAX_LINE_CHARS] for line in lines if needle.search(line)]
    return {
        "service": service,
        "scanned_lines": len(lines),
        "matches": len(hits),
        "shown": len(hits[:MAX_MATCHES]),
        "lines": hits[:MAX_MATCHES],
    }


def logs_services(cfg: Config) -> dict[str, Any]:
    """Which systems are sending logs at all — the menu for `logs_query`."""
    with httpx.Client(base_url=cfg.loki.base_url, timeout=30.0) as http:
        response = http.get("/loki/api/v1/label/service/values")
    return {"services": sorted(response.json().get("data", []) or [])}


def feed_list_files(cfg: Config) -> dict[str, Any]:
    """What the ERP has dropped for the integration to pick up."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            cfg.feed.host,
            port=cfg.feed.port,
            username=cfg.feed.user,
            password=cfg.feed.password,
            look_for_keys=False,
            allow_agent=False,
        )
        with client.open_sftp() as sftp:
            return {
                "directory": cfg.feed.directory,
                "files": sorted(sftp.listdir(cfg.feed.directory)),
            }
    finally:
        client.close()


def feed_read_file(cfg: Config, name: str) -> dict[str, Any]:
    """One feed file, as the integration would read it."""
    import paramiko

    safe = name.split("/")[-1]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            cfg.feed.host,
            port=cfg.feed.port,
            username=cfg.feed.user,
            password=cfg.feed.password,
            look_for_keys=False,
            allow_agent=False,
        )
        with client.open_sftp() as sftp:
            with sftp.open(f"{cfg.feed.directory}/{safe}") as handle:
                body = handle.read().decode("utf-8", "replace")
    finally:
        client.close()

    clipped = body[:MAX_FEED_CHARS]
    result: dict[str, Any] = {"file": safe, "chars": len(body), "content": clipped}
    if len(body) > MAX_FEED_CHARS:
        result["truncated"] = f"showing {MAX_FEED_CHARS} of {len(body)} characters"
    return result


def _matomo_params(cfg: Config, method: str) -> dict[str, str]:
    return {
        "module": "API",
        "format": "JSON",
        "idSite": cfg.matomo.site_id,
        "token_auth": cfg.matomo.token,
        "method": method,
    }


def _matomo(cfg: Config, method: str, params: dict[str, Any] | None = None) -> Any:
    """One Matomo call, with its refusals treated as refusals.

    Matomo answers an error with **HTTP 200** and `{"result": "error"}`. Handing
    that back as data is how "your token is wrong" becomes "there were no
    visits", so the shape is checked rather than the status code.
    """
    query = {
        **_matomo_params(cfg, method),
        **{k: str(v) for k, v in (params or {}).items()},
    }
    with httpx.Client(base_url=cfg.matomo.base_url, verify=False, timeout=60.0) as http:
        response = http.get("/index.php", params=query)
    if response.status_code >= 400:
        return {"error": f"HTTP {response.status_code}", "body": response.text[:600]}
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {"error": "not JSON", "body": response.text[:600]}
    if isinstance(payload, dict) and payload.get("result") == "error":
        return {"error": payload.get("message", "Matomo refused the call")}
    return payload


def analytics_reports(cfg: Config) -> dict[str, Any]:
    """Which reports Matomo has, from Matomo itself rather than a list kept here."""
    payload = _matomo(cfg, "API.getReportMetadata")
    if isinstance(payload, dict) and "error" in payload:
        return payload
    reports = [
        {
            "method": f"{item.get('module')}.{item.get('action')}",
            "name": item.get("name"),
        }
        for item in payload
        if isinstance(item, dict) and item.get("action")
    ]
    # `total` here was honest — the whole catalogue is in hand — but silent
    # about having been cut, so a reader saw 25 of 77 with nothing to say so.
    return {"resource": "reports", **bounded.window(reports, cap=MAX_ROWS)}


def analytics_get(
    cfg: Config, method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call one Matomo method with its own parameters."""
    payload = _matomo(cfg, method, params)
    if isinstance(payload, dict):
        return payload
    # Matomo was asked for a bounded page via `filter_limit`, so what came
    # back is what it chose to send and the remainder is genuinely unknown.
    return {
        "method": method,
        **bounded.window(payload, cap=MAX_ROWS, server_capped=True),
    }
