"""The application cartography — the catalog of the simulated company's apps and the
flows between them, plus a live health probe. This is the company-specific config;
a different simulated company would ship a different catalog.

Tiers: public (no sign-in) · enterprise (back-office, sign-in) · roadmap (planned).
"""

import asyncio
from typing import Any

import httpx

from app.config import settings

APPS: list[dict[str, Any]] = [
    {
        "id": "storefront",
        "name": "Storefront",
        "sub": "the shop customers see",
        "tier": "public",
        "url": settings.storefront_url,
        "thumb": "storefront",
        "blurb": "The PrestaShop storefront, the public shop the simulated customers browse and buy from.",
    },
    {
        "id": "backoffice",
        "name": "Back-office",
        "sub": "PrestaShop admin",
        "tier": "enterprise",
        "url": settings.backoffice_url,
        "thumb": "backoffice",
        # TODO: generate a dedicated read-only back-office user and surface it here.
        "login": {"user": "<TODO>", "password": "<TODO>"},
        "blurb": "The PrestaShop back-office for catalogue, orders, customers and stats.",
    },
    {
        "id": "analytics",
        "name": "Web Analytics",
        "sub": "Matomo",
        "tier": "enterprise",
        "url": settings.analytics_url,
        "thumb": "matomo",
        # TODO: generate a dedicated read-only Matomo view user and surface it here.
        "login": {"user": "<TODO>", "password": "<TODO>"},
        "blurb": "Matomo web analytics for visits, behaviour and funnels on the storefront.",
    },
    {
        "id": "pim",
        "name": "PIM",
        "tier": "roadmap",
        "blurb": "Product information management, one source of truth for the catalogue.",
    },
    {
        "id": "erp",
        "name": "ERP",
        "tier": "roadmap",
        "blurb": "Enterprise resource planning for orders, finance and operations.",
    },
    {
        "id": "inventory",
        "name": "Inventory",
        "tier": "roadmap",
        "blurb": "Stock levels across locations.",
    },
    {
        "id": "accounting",
        "name": "Accounting",
        "tier": "roadmap",
        "blurb": "Ledgers, invoicing, reconciliation.",
    },
    {
        "id": "suppliers",
        "name": "Suppliers",
        "tier": "roadmap",
        "blurb": "Procurement and EDI with suppliers.",
    },
    {
        "id": "pos",
        "name": "POS",
        "tier": "roadmap",
        "blurb": "Point of sale for physical stores.",
    },
    {
        "id": "stores",
        "name": "Stores",
        "tier": "roadmap",
        "blurb": "Physical store operations for the omnichannel endpoint.",
    },
]

FLOWS: list[dict[str, Any]] = [
    {"from": "storefront", "to": "analytics", "label": "PAGE VIEWS", "kind": "live"},
    {
        "from": "storefront",
        "to": "backoffice",
        "label": "CATALOG · ORDERS",
        "kind": "live",
        "bidir": True,
    },
    {"from": "pim", "to": "backoffice", "label": "PRODUCTS", "kind": "planned"},
    {"from": "backoffice", "to": "erp", "label": "ORDERS", "kind": "planned"},
]

# Internal URL to probe for each live app's health (service names on the shared net).
_PROBE = {
    "storefront": "http://prestashop:80/",
    "backoffice": "http://prestashop:80/",
    "analytics": "http://matomo:80/",
}


async def _reachable(client: httpx.AsyncClient, url: str) -> bool:
    try:
        await client.get(url, timeout=2.5)
        return True
    except Exception:
        return False


async def _health() -> dict[str, str]:
    urls = list(set(_PROBE.values()))
    async with httpx.AsyncClient(follow_redirects=False) as client:
        reached = await asyncio.gather(*(_reachable(client, u) for u in urls))
    up = dict(zip(urls, reached, strict=True))
    return {aid: ("up" if up.get(probe) else "down") for aid, probe in _PROBE.items()}


async def catalog() -> dict[str, Any]:
    status = await _health()
    apps = [{**a, "status": status.get(a["id"], "planned")} for a in APPS]
    return {"apps": apps, "flows": FLOWS}
