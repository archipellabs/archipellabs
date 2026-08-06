"""Every query parameter the shop tool advertises, checked against the real API.

Written after a run diagnosed a "corrupted order record causing a poison-pill on
descending scans", with high confidence, from nothing. The whole story rested on
one observation — `sort=[id_DESC]` returning zero rows — which was real, and was
a *tool* defect: PrestaShop answers `{"orders": []}` for a sort it will not
honour, so "no data" and "I ignored your query" look identical.

The lesson is not "the model hallucinated". A tool that cannot say *I did not
understand you* manufactures evidence, and a good investigator will build a
mechanism to explain it. So these tests exist to make sure the tool's docstring
and the shop's behaviour cannot drift apart: every parameter we tell the agent
about is exercised here against the live shop, and any that stops working fails
the suite instead of becoming someone's root cause.

Live by necessity — the bug was PrestaShop's behaviour, and no fake reproduces it:

    uv run pytest -m live
"""

import os
import pathlib
from collections.abc import AsyncIterator

import httpx
import pytest

from core.config import load
from roles.angel.tools import shop

pytestmark = pytest.mark.live


def _load_env() -> None:
    path = pathlib.Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    _load_env()
    async with shop.client(load().shop) as client:
        yield client


async def test_the_directory_lists_what_an_investigation_needs(http):
    """`resources` is the entry point: if it stops naming these, discovery dies."""
    names = {r["resource"] for r in await shop.resources(http)}

    assert {"orders", "deliveries", "zones", "countries", "carriers"} <= names


async def test_a_resource_reports_its_real_fields(http):
    """`deliveries` is how "can we ship to Canada" is answered, and only via
    id_zone — if the schema stops exposing it, the join is undiscoverable."""
    schema = await shop.schema(http, "deliveries")

    assert schema["entity"] == "delivery"
    assert {"id_carrier", "id_zone", "price"} <= set(schema["fields"])


async def test_an_unknown_resource_says_so_rather_than_looking_empty(http):
    result = await shop.schema(http, "not_a_resource")

    assert "error" in result


async def test_a_limited_read_cannot_claim_to_be_the_whole_truth(http):
    """This test used to assert `total == 3` for `limit=3` against 700 orders,
    engraving the ambiguity into the contract. The shop capped it and does not
    report what it withheld, so completeness is unknown and there is no total."""
    result = await shop.get(http, "orders", {"limit": 3})

    assert result["returned"] == 3
    assert result["complete"] == "unknown"
    assert "total" not in result


async def test_display_selects_fields(http):
    result = await shop.get(
        http, "countries", {"display": ["id", "iso_code"], "limit": 2}
    )

    assert result["rows"], "expected at least one country"
    assert set(result["rows"][0]) == {"id", "iso_code"}


async def test_filter_narrows_to_matching_rows(http):
    result = await shop.get(
        http, "countries", {"filter": {"iso_code": "CA"}, "display": ["iso_code"]}
    )

    assert result["total"] == 1
    assert result["rows"][0]["iso_code"] == "CA"


async def test_the_shop_still_swallows_every_sort_it_is_sent(http):
    """The premise the tool is built on, pinned against the live shop.

    Sent to PrestaShop, `sort` answers HTTP 200 with zero rows — verified across
    every encoding: bracketed, unbracketed, with the field displayed, with
    `date=1`. If a shop upgrade ever fixes this, that is worth knowing
    deliberately rather than discovering through a behaviour change, so the tool
    stops sending it and this test guards the reason.
    """

    def rows(response: httpx.Response) -> list[dict[str, object]]:
        # A hit is `{"orders": [...]}` and a miss is a bare `[]` — the shape
        # changes with the result count, which is half of why a swallowed sort
        # was indistinguishable from "no such rows" in the first place.
        payload = response.json()
        return payload.get("orders", []) if isinstance(payload, dict) else payload

    control = await http.get("/orders", params={"limit": "5"})
    sorted_away = await http.get("/orders", params={"limit": "5", "sort": "[id_DESC]"})

    assert control.status_code == 200 and sorted_away.status_code == 200
    assert rows(control), "the control must have rows to compare"
    assert not rows(sorted_away), (
        "the shop began honouring sort — the tool can stop doing it itself"
    )


async def test_sort_orders_the_rows_the_shop_would_not(http):
    """What the agent gets now: `id_DESC` on `orders` — the exact query that once
    returned nothing and grew a fabricated root cause — answers newest first."""
    descending = await shop.get(http, "orders", {"sort": ["id_DESC"], "limit": 5})
    ascending = await shop.get(http, "orders", {"sort": ["id_ASC"], "limit": 5})

    ids = [int(row["id"]) for row in descending["rows"]]
    assert ids == sorted(ids, reverse=True)
    assert int(ids[0]) > int(ascending["rows"][0]["id"])
    assert descending["sorted"]["by"] == ["id_DESC"]


async def test_the_newest_rows_are_the_newest_of_all_of_them(http):
    """The trap this replaced a dead end with, if done naively. Rows arrive
    id-ascending, so the five the shop returns for `limit=5` are the five
    oldest; ordering those descending answers "the newest of the oldest five".
    The count comes from the whole set, so it can be checked."""
    newest = await shop.get(http, "orders", {"sort": ["id_DESC"], "limit": 5})

    # The oracle goes straight to the shop, because `shop_get` caps what it
    # *shows* at MAX_ROWS: reading the newest id out of its `rows` would compare
    # the answer against page one, which is the very mistake under test.
    raw = await http.get("/orders", params={"display": "[id]"})
    payload = raw.json()
    every_id = [int(row["id"]) for row in payload["orders"]]

    assert newest["total"] > 5, "there must be more rows than the slice"
    assert newest["total"] == len(every_id)
    assert int(newest["rows"][0]["id"]) == max(every_id), (
        "the first row must be the newest in the shop, not the newest on page one"
    )


async def test_a_field_the_shop_will_not_display_says_which_ones_it_would(http):
    """`carts` advertises `associations` and refuses to list it — a 500 whose
    body names every field that would have worked. That explanation reaching the
    agent intact is the whole point: truncated to `HTTP 500`, two graded runs
    read it as a server fault and reported it as the incident."""
    result = await shop.get(http, "carts", {"display": ["id", "associations"]})

    assert "error" in result
    assert "these are available" in result["error"], "the shop's own words"
    assert "HTTP" not in result["error"], "the status is a detail, not the message"
    assert result["shop_code"] == 35


async def test_a_genuinely_empty_result_is_still_empty(http):
    """The guard must not turn "nothing matched" into an error."""
    result = await shop.get(
        http, "countries", {"filter": {"iso_code": "ZZ"}, "sort": ["id_DESC"]}
    )

    assert result.get("total") == 0
    assert "error" not in result


async def test_a_truncated_read_declares_itself_and_offers_the_next_page(http):
    """A run read the first hundred orders, saw nothing recent, and reported that
    sales had stopped. `complete: false` plus `next_offset` is the neutral fact
    that prevents it — no prose assuming every resource is chronological."""
    result = await shop.get(http, "orders")

    assert result["total"] > shop.MAX_ROWS, "expected many shop orders"
    assert result["complete"] is False
    assert result["returned"] == shop.MAX_ROWS
    assert result["next_offset"] == shop.MAX_ROWS


async def test_offset_paging_reaches_the_newest_rows(http):
    """The escape hatch that note points at. If it breaks, recent orders become
    unreachable and "orders stopped" becomes the only available conclusion."""
    total = (await shop.get(http, "orders", {"display": ["id"]}))["total"]
    first = await shop.get(http, "orders", {"display": ["id"], "limit": 5})
    last = await shop.get(
        http, "orders", {"display": ["id"], "limit": f"{total - 5},5"}
    )

    assert int(last["rows"][-1]["id"]) > int(first["rows"][0]["id"])


async def test_a_date_filter_finds_orders_in_a_window(http):
    """The other route to "what happened lately", and the one a human would use."""
    result = await shop.get(
        http,
        "orders",
        {
            "display": ["id", "date_add"],
            "date": 1,
            "filter": {"date_add": "[2026-01-01 00:00:00,2036-12-31 23:59:59]"},
            "limit": 3,
        },
    )

    assert result["returned"] == 3, "the date filter must not silently return nothing"


async def test_timestamps_are_labelled_with_the_shop_zone(http):
    """The trap that cost a run: an order at 14:30 shop-time against a log line at
    19:28 UTC reads as five hours of silence. The agent cannot look the zone up —
    `configurations` is refused to a read-only key — so the tool must say it."""
    result = await shop.get(http, "orders", {"display": ["id", "date_add"], "limit": 3})

    assert "America/Chicago" in result["time_note"]


async def test_no_timezone_note_when_no_timestamps_come_back(http):
    """It appears where the trap exists and nowhere else, or it becomes wallpaper."""
    result = await shop.get(http, "countries", {"display": ["id"], "limit": 3})

    assert "window" not in result
    assert "time_note" not in result
