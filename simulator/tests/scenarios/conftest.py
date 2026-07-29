"""Scenario fixtures — editing the company's master data, and waiting for it to land.

A scenario is a level above e2e. An e2e test drives one flow against a live
service; a scenario changes what the *company* believes, waits for the
integration layer to reconcile the storefront, and then asks whether a customer
can still buy. The subject is the whole stack, and the assertion is a business
outcome rather than an API response.

That means these tests mutate a file in the repository. Every mutation goes
through `master_data`, which restores the original content afterwards even if the
test fails — a scenario that leaves the shop broken is worse than one that fails.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx
import pytest

from src.internal_flows.catalog.client import json_client

# simulator/tests/scenarios/conftest.py → repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
FEED_DIR = REPO_ROOT / "sidecars" / "erpfile" / "data"

# The integration layer polls the feed every 30s; this is that plus room for the
# reconcile itself. Generous on purpose — a flaky scenario teaches nothing.
RECONCILE_TIMEOUT_S = 150.0


@pytest.fixture
def master_data() -> Iterator[Callable[[str, str], None]]:
    """Edit a master-data file, and put it back afterwards.

    Yields `edit(filename, new_content)`. Originals are captured on first touch
    and restored on teardown, so a scenario can leave the file in any state and
    the next one still starts from a healthy company.
    """
    originals: dict[Path, str] = {}

    def edit(filename: str, content: str) -> None:
        path = FEED_DIR / filename
        if path not in originals:
            originals[path] = path.read_text()
        path.write_text(content)

    yield edit

    for path, text in originals.items():
        path.write_text(text)


@pytest.fixture
def read_feed() -> Callable[[str], str]:
    def _read(filename: str) -> str:
        return (FEED_DIR / filename).read_text()

    return _read


@pytest.fixture
async def shop() -> AsyncIterator[httpx.AsyncClient]:
    """The Webservice, for asking the shop what it currently believes."""
    async with json_client() as client:
        yield client


async def carrier_zones(shop: httpx.AsyncClient, carrier_name: str) -> set[int]:
    """Zone ids this carrier currently quotes a price for.

    Coverage alone does not make a carrier available — a zone with no delivery
    row quotes nothing and the storefront offers no method at all. So the
    delivery rows are what "does this carrier serve that country" actually means.
    """
    found = await shop.get(
        "/carriers",
        params={"display": "[id]", "filter[name]": carrier_name, "filter[deleted]": 0},
    )
    found.raise_for_status()
    data = found.json()
    # An empty result is a bare [] rather than {"carriers": []}.
    if isinstance(data, list) or not data.get("carriers"):
        return set()

    carrier_id = int(data["carriers"][0]["id"])
    rows = await shop.get(
        "/deliveries",
        params={"display": "[id_zone]", "filter[id_carrier]": carrier_id},
    )
    rows.raise_for_status()
    payload = rows.json()
    if isinstance(payload, list):
        return set()
    return {int(row["id_zone"]) for row in payload.get("deliveries", [])}


async def delivery_rows(shop: httpx.AsyncClient, carrier_name: str) -> dict[int, int]:
    """This carrier's delivery rows, as {zone id: row id}.

    The row *ids* are what tell a merge apart from a rebuild. A sync that wipes
    each carrier's pricing and recreates it produces the same zones with fresh
    ids every run — and leaves the shop quoting nothing in between. A sync that
    updates rows in place keeps them. Only the second is safe to run against a
    shop that is open, which is why this is asserted rather than assumed.
    """
    found = await shop.get(
        "/carriers",
        params={"display": "[id]", "filter[name]": carrier_name, "filter[deleted]": 0},
    )
    found.raise_for_status()
    data = found.json()
    if isinstance(data, list) or not data.get("carriers"):
        return {}

    rows = await shop.get(
        "/deliveries",
        params={
            "display": "[id,id_zone]",
            "filter[id_carrier]": int(data["carriers"][0]["id"]),
        },
    )
    rows.raise_for_status()
    payload = rows.json()
    if isinstance(payload, list):
        return {}
    return {int(r["id_zone"]): int(r["id"]) for r in payload.get("deliveries", [])}


async def zone_of(shop: httpx.AsyncClient, iso_code: str) -> int:
    """Which zone the shop puts a country in — the shop decides, not the feed."""
    response = await shop.get(
        "/countries",
        params={"display": "[id_zone]", "filter[iso_code]": iso_code},
    )
    response.raise_for_status()
    return int(response.json()["countries"][0]["id_zone"])


async def until_serving(
    shop: httpx.AsyncClient,
    carrier_name: str,
    zones: set[int],
    *,
    timeout: float = RECONCILE_TIMEOUT_S,
) -> None:
    """Wait until this carrier serves exactly `zones` — no more, no fewer.

    Scenarios are asynchronous by nature: the file changes, and some seconds
    later the shop does. Polling is the honest way to observe that; sleeping a
    fixed interval would be either flaky or slow.

    The *whole set* matters, and waiting on one zone would be quietly wrong. The
    route upserts each row and prunes the rest in a later pass, so a wait for
    "Canada is gone" can return before the prune has finished and the shop has
    settled. An exact set can only match once the whole reconcile is done.
    """
    deadline = time.monotonic() + timeout
    while True:
        serving = await carrier_zones(shop, carrier_name)
        if serving == zones:
            return
        if time.monotonic() > deadline:
            raise AssertionError(
                f"after {timeout:.0f}s, {carrier_name} serves zones "
                f"{sorted(serving)} and should serve {sorted(zones)} — "
                "is the camel container running?"
            )
        await asyncio.sleep(2)
