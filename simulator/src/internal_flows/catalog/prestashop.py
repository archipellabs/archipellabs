"""Async helpers for PrestaShop's Webservice API.

Shared by the catalog sync logic. Reads go through the JSON client
(`Output-Format: JSON`); writes build PrestaShop XML with ElementTree — values are
escaped by the serializer, not hand-wrapped in CDATA — then POST/PUT it.
"""

import logging
import mimetypes
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from src.config import settings

log = logging.getLogger("simulator.catalog")

LANG_ID = int(settings.prestashop_webservice_language_id)
_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'


def lang_value(value: Any) -> str:
    """The current-language string of a PS multilingual field: [{id, value}, …]."""
    if isinstance(value, list):
        for item in value:
            if item.get("id") == LANG_ID:
                return item.get("value", "")
    return ""


async def get_all(http: httpx.AsyncClient, resource: str) -> list[dict[str, Any]]:
    """Every object of a resource, paginated, via `display=full` (JSON)."""
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        r = await http.get(
            f"/{resource}", params={"display": "full", "limit": 100, "page": page}
        )
        if r.status_code != 200:
            break
        data = r.json()
        if isinstance(data, list):  # empty resource → []
            break
        batch = data.get(resource, [])
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


# ── XML builders (ElementTree → escaped, valid XML) ──────────────────────────


def field(tag: str, value: object) -> ET.Element:
    """A simple element: ``<tag>value</tag>``."""
    el = ET.Element(tag)
    el.text = str(value)
    return el


def lang(tag: str, value: str) -> ET.Element:
    """A multilingual element: ``<tag><language id="N">value</language></tag>``."""
    el = ET.Element(tag)
    ET.SubElement(el, "language", id=str(LANG_ID)).text = value
    return el


def lang_multi(tag: str, values: dict[int, str]) -> ET.Element:
    """A multilingual element with one ``<language id="N">`` child per language id."""
    el = ET.Element(tag)
    for lang_id, value in values.items():
        ET.SubElement(el, "language", id=str(lang_id)).text = value
    return el


def id_list(wrapper: str, child: str, ids: Iterable[int]) -> ET.Element:
    """An association list: ``<wrapper><child><id>N</id></child>…</wrapper>``."""
    el = ET.Element(wrapper)
    for i in ids:
        ET.SubElement(ET.SubElement(el, child), "id").text = str(i)
    return el


def associations(*blocks: ET.Element) -> ET.Element:
    el = ET.Element("associations")
    el.extend(blocks)
    return el


def wrap(resource: str, *children: ET.Element) -> str:
    """Serialise `children` inside the ``<prestashop><resource>`` envelope."""
    root = ET.Element("prestashop", {"xmlns:xlink": "http://www.w3.org/1999/xlink"})
    ET.SubElement(root, resource).extend(children)
    return _XML_DECL + ET.tostring(root, encoding="unicode")


# ── HTTP ─────────────────────────────────────────────────────────────────────


async def _write(
    http: httpx.AsyncClient, method: str, path: str, body: str
) -> httpx.Response | None:
    """POST/PUT XML; return the response, or None if PrestaShop rejected it."""
    r = await http.request(
        method,
        path,
        content=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        timeout=15,
    )
    if r.status_code not in (200, 201):
        log.warning("%s %s → %d: %s", method, path, r.status_code, r.text[:300])
        return None
    return r


async def post(http: httpx.AsyncClient, resource: str, body: str) -> ET.Element | None:
    r = await _write(http, "POST", f"/{resource}", body)
    return ET.fromstring(r.content) if r is not None else None


async def put(http: httpx.AsyncClient, resource: str, rid: int, body: str) -> bool:
    return await _write(http, "PUT", f"/{resource}/{rid}", body) is not None


def resource_id(root: ET.Element | None) -> int | None:
    """The resource id from a PS XML response (``<prestashop><x><id>…``)."""
    if root is None:
        return None
    try:
        val = root[0].findtext("id", "").strip()
        return int(val) if val else None
    except (IndexError, ValueError):
        return None


async def upload_image(
    http: httpx.AsyncClient, product_id: int, path: Path
) -> int | None:
    """Upload a product image; return its PS image id (None on miss/failure)."""
    if not path.exists():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    with path.open("rb") as f:
        r = await http.post(
            f"/images/products/{product_id}",
            files={"image": (path.name, f, mime)},
        )
    if r.status_code not in (200, 201):
        log.warning("image upload for product %d → %d", product_id, r.status_code)
        return None
    return resource_id(ET.fromstring(r.content) if r.content else None)
