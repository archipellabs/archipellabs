"""The application cartography — the catalog of the simulated company's apps and the
flows between them, plus a live health probe. This is the company-specific config;
a different simulated company would ship a different catalog.

Tiers: public (no sign-in) · enterprise (back-office, sign-in) · platform (data and
observability) · roadmap (planned).

**No card publishes a credential today.** Working demo passwords exist in the
workspace's committed env files, but every one of them is an admin, and this page
is public. Each card that needs a sign-in carries a `todo` naming the read-only
account still to be provisioned; `login` is the field they will use once those
accounts exist, and nothing sets it in the meantime.
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
        # Deliberately not the workspace admin: this page is public. A dedicated
        # read-only user is the thing to provision, and until it exists the card
        # says so rather than offering a credential nobody can use.
        "todo": "a dedicated read-only back-office user is not provisioned yet",
        "blurb": "The PrestaShop back-office for catalogue, orders, customers and stats.",
    },
    {
        "id": "analytics",
        "name": "Web Analytics",
        "sub": "Matomo",
        "tier": "enterprise",
        "url": settings.analytics_url,
        "thumb": "matomo",
        "todo": "a dedicated read-only Matomo view user is not provisioned yet",
        "blurb": "Matomo web analytics for visits, behaviour and funnels on the storefront.",
    },
    # --- the platform: what carries the data and what watches the company -----
    #
    # These have no storefront and mostly no screen. They are on the chart
    # because an incident lives here as often as it lives in an application, and
    # a map that stops at the applications sends somebody looking in the wrong
    # half of the company.
    {
        "id": "erp",
        "name": "ERP",
        "sub": "SFTP drop",
        "tier": "platform",
        "thumb": None,
        "blurb": (
            "The system of record for reference data — carriers, suppliers — as CSV files "
            "on an SFTP drop. The name is the role, not the implementation: a real ERP "
            "would sit here and the rest of the company would not notice. It keeps no "
            "history; each file is the current state and nothing beside it says what "
            "changed."
        ),
    },
    {
        "id": "integration",
        "name": "Integration",
        "sub": "Apache Camel",
        "tier": "platform",
        "thumb": None,
        "blurb": (
            "Carries master data from the ERP drop into the shop, reconciling the "
            "difference rather than replaying it: a row absent upstream is deleted "
            "downstream. That reconciliation is the only record of the change, it is "
            "written once, and it ages out of any ordinary log window."
        ),
    },
    {
        "id": "collector",
        "name": "Collector",
        "sub": "Grafana Alloy",
        "tier": "platform",
        "thumb": None,
        "blurb": (
            "Scrapes logs and metrics from every service above and forwards them. "
            "Deliberately blind to the simulator itself, which is the instrument rather "
            "than part of the company."
        ),
    },
    {
        "id": "logs",
        "name": "Logs",
        "sub": "Loki",
        "tier": "platform",
        "thumb": None,
        "blurb": (
            "What the running services wrote, including the ones that sit between "
            "systems. Queried by label rather than browsed — and the set of services is "
            "worth asking for rather than assuming, because it grows."
        ),
    },
    {
        "id": "metrics",
        "name": "Metrics",
        "sub": "Prometheus",
        "tier": "platform",
        "thumb": None,
        "blurb": "Time series for the company's services — rates, saturation, errors.",
    },
    {
        "id": "dashboards",
        "name": "Dashboards",
        "sub": "Grafana",
        "tier": "platform",
        "url": settings.dashboards_url,
        "thumb": None,
        # No credential published here either, though this one has a working
        # demo password in `config/monitoring/default.env`. What that password
        # opens is an admin, and an admin handed out on a public page is a
        # different offer from the read-only viewer this card is meant to carry.
        # It goes back in when that account exists — see `todo` on every card
        # that needs a sign-in.
        "todo": "a dedicated read-only Grafana viewer is not provisioned yet",
        "blurb": "Grafana over the logs and the metrics — the one screen this half of the company has.",
    },
    {
        "id": "pim",
        "name": "PIM",
        "tier": "roadmap",
        "blurb": "Product information management, one source of truth for the catalogue.",
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
    # The master-data lane, and the one this lab's first incident travels down:
    # a row leaves the drop, the integration reconciles, and the shop quietly
    # stops offering something.
    {"from": "erp", "to": "integration", "label": "FEED", "kind": "live"},
    {"from": "integration", "to": "backoffice", "label": "RECONCILE", "kind": "live"},
    # The observability lane. What feeds the collector is *every* service above,
    # which is a relation this chart cannot draw without lying about which ones —
    # so the region's own note says it instead of an arrow claiming one source.
    {"from": "collector", "to": "logs", "label": "", "kind": "live"},
    {"from": "collector", "to": "metrics", "label": "", "kind": "live"},
    {"from": "logs", "to": "dashboards", "label": "", "kind": "live"},
    {"from": "metrics", "to": "dashboards", "label": "", "kind": "live"},
    {"from": "pim", "to": "backoffice", "label": "PRODUCTS", "kind": "planned"},
]

# Internal URL to probe for each live app's health (service names on the shared net).
_PROBE = {
    "storefront": "http://prestashop:80/",
    "backoffice": "http://prestashop:80/",
    "analytics": "http://matomo:80/",
    "dashboards": "http://grafana:3000/api/health",
    "metrics": "http://prometheus:9090/-/healthy",
    "collector": "http://alloy:12345/-/ready",
    # **Not `/ready`.** This deployment's Loki answers that with a permanent 503
    # — "Ingester not ready" — while serving every query put to it. A readiness
    # endpoint that reports a working service as down is worse than no probe, so
    # this asks the question that matters instead: can its logs be queried.
    "logs": "http://loki:3100/loki/api/v1/labels",
}

# Ports to open a socket against, for what speaks no HTTP.
_LISTENS = {"erp": ("erpfile", 22)}

_UNOBSERVABLE = {"integration"}
"""Live, and with no way from here to confirm it. Reported as `unknown`.

The integration runtime exposes no port at all, so nothing can be asked. It does
have a heartbeat — a route logs one every thirty seconds — but at DEBUG, which
this deployment does not ship, and deliberately: *a heartbeat is worth having and
not worth reading*, because two lines a minute of "nothing is happening" is what
an analyst grepping the integration for a change has to scroll past. Raising it
to INFO would make this probe easy and make the log worse, which is the wrong
trade in a lab whose whole subject is what an investigator can find.

So its lane is drawn and its light is left grey. **A third state is the honest
answer here**: green without a check and red for a service that is fine are both
lies, and the second is the more expensive — it sends somebody to look at the one
component that has nothing wrong with it."""


async def _reachable(client: httpx.AsyncClient, url: str) -> bool:
    try:
        response = await client.get(url, timeout=2.5)
    except Exception:
        return False
    # A reply of any kind used to count, which made a 500 from a crashed app look
    # exactly like health. The probes above are chosen so that success is a 2xx.
    return response.status_code < 400


async def _listening(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.5
        )
    except Exception:
        return False
    writer.close()
    return True


async def _health() -> dict[str, str]:
    urls = list(set(_PROBE.values()))
    async with httpx.AsyncClient(follow_redirects=False) as client:
        reached, sockets = await asyncio.gather(
            asyncio.gather(*(_reachable(client, u) for u in urls)),
            asyncio.gather(*(_listening(h, p) for h, p in _LISTENS.values())),
        )
    up = dict(zip(urls, reached, strict=True))
    status = {aid: ("up" if up.get(probe) else "down") for aid, probe in _PROBE.items()}
    status |= {
        aid: ("up" if ok else "down") for aid, ok in zip(_LISTENS, sockets, strict=True)
    }
    return status | dict.fromkeys(_UNOBSERVABLE, "unknown")


async def catalog() -> dict[str, Any]:
    status = await _health()
    apps = [{**a, "status": status.get(a["id"], "planned")} for a in APPS]
    return {"apps": apps, "flows": FLOWS}
