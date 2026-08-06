"""The shop tool against a fake PrestaShop.

The live suite proves these parameters work on the real shop. This one covers
what a healthy shop will not produce on demand: a 500 mid-investigation, an
HTML error page, a sort silently swallowed. Every one of those has already
produced a wrong answer once.
"""

import json

import httpx
import pytest

from roles.angel.tools import shop
from tests.angel.conftest import transport

BLANK_SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<prestashop><delivery><id/><id_carrier/><id_zone/><price/></delivery></prestashop>"""

DIRECTORY = """<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink"><api shopName="PrestaShop">
<deliveries xlink:href="x" get="true" put="false" head="true">
<description>Product delivery</description></deliveries>
<orders get="true" head="true"><description>The Customer orders</description></orders>
</api></prestashop>"""


def _http(handler, cfg) -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=cfg.base_url, transport=transport(handler))
    client.shop_timezone = cfg.timezone  # type: ignore[attr-defined]
    return client


# ── _wire: the encoding a model actually sends ───────────────────────────────


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"limit": 5}, {"limit": "5"}),
        ({"display": ["id", "name"]}, {"display": "[id,name]"}),
        ({"sort": ["id_DESC"]}, {"sort": "[id_DESC]"}),
        ({"filter": {"iso_code": "CA"}}, {"filter[iso_code]": "CA"}),
        ({"date": True}, {"date": "1"}),
        ({"date": False}, {"date": "0"}),
        ({"limit": "80,100"}, {"limit": "80,100"}),
        ({"display": "full"}, {"display": "full"}),
        ({"filter": {"a": 1, "b": 2}}, {"filter[a]": "1", "filter[b]": "2"}),
    ],
)
def test_wire_encodes_natural_json_into_prestashop_syntax(given, expected):
    """A model sends lists and numbers. Rejecting them as type errors cost a run
    a third of its budget guessing at string spellings."""
    assert shop._wire(given) == expected


def test_wire_leaves_an_empty_query_empty():
    assert shop._wire({}) == {}


# ── get: shapes, failures, and the two notes ─────────────────────────────────


async def test_a_bare_list_means_nothing_matched(shop_cfg):
    """PrestaShop answers `[]` on a miss and `{"orders": [...]}` on a hit, so the
    shape changes with the result count."""

    def handler(request):
        return httpx.Response(200, json=[])

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["total"] == 0
    assert result["rows"] == []
    assert "error" not in result


async def test_a_refusal_speaks_the_shop_s_words_not_its_status_code(shop_cfg):
    """This test used to assert `error == "HTTP 500"` with the explanation in
    `body`, and that shape cost two graded runs: the model read the status first
    and concluded the server was broken. Worse, `body` was cut at the row budget
    of 200 while the real message runs to 970, so the list of valid fields ended
    mid-word. The message the shop wrote IS the error."""
    body = (
        '{"errors":[{"code":35,"message":"Unable to display this field '
        '\\"associations\\". However, these are available: id, date_add"}]}'
    )

    def handler(request):
        return httpx.Response(500, text=body)

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "carts", {"display": ["id", "associations"]})

    assert result["error"].startswith("Unable to display this field")
    assert "these are available: id, date_add" in result["error"]
    assert result["shop_code"] == 35
    assert result["http"] == 500


async def test_a_real_sized_refusal_keeps_the_part_that_says_what_to_do(shop_cfg):
    """Sized like the shop's actual `carts` refusal — 970 characters, whose
    actionable half is the field list at the end. Cut to the old row budget of
    200, that end was lost. The fixture is deliberately as long as reality: the
    reason this defect survived its tests was a 101-character fixture that fit
    comfortably under a cut the real message did not."""
    fields = ", ".join(f"id_field_{n}" for n in range(70))
    body = json.dumps(
        {"errors": [{"code": 35, "message": f"Unable to display. Available: {fields}"}]}
    )

    def handler(request):
        return httpx.Response(500, text=body)

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "carts", {"display": ["nope"]})

    assert 900 < len(body) < 1100, "the fixture must be the size of the real thing"
    assert "id_field_69" in result["error"], "the end of the list is the useful end"


async def test_a_refusal_too_long_to_keep_says_that_it_was_cut(shop_cfg):
    """A cut that does not announce itself is how "these are the valid fields"
    becomes a shorter, wrong list — the same silent-truncation defect one level
    down."""
    fields = ", ".join(f"id_field_{n}" for n in range(300))
    body = json.dumps({"errors": [{"code": 35, "message": f"Available: {fields}"}]})

    def handler(request):
        return httpx.Response(500, text=body)

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "carts", {"display": ["nope"]})

    assert "cut here" in result["error"]
    assert "incomplete" in result["error"]


async def test_an_unparseable_error_still_reports_the_status(shop_cfg):
    """A gateway or PHP fatal answers with no JSON envelope at all."""

    def handler(request):
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["error"] == "HTTP 502"
    assert "Bad Gateway" in result["body"]


async def test_an_html_error_page_does_not_raise(shop_cfg):
    def handler(request):
        return httpx.Response(200, text="<html>Fatal error</html>")

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["error"] == "not JSON"


async def test_sort_is_never_sent_to_a_shop_that_swallows_it(shop_cfg):
    """The shop answers 200-and-no-rows for every sort encoding, on every
    resource an investigation needs. The tool used to detect that and report it,
    which was true and still a dead end — 22 refusals across ten graded runs, 17
    of which ended the line of inquiry. So the parameter stays here."""
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        if "sort" in dict(request.url.params):
            return httpx.Response(200, json={"orders": []})
        return httpx.Response(200, json={"orders": [{"id": 1}, {"id": 3}, {"id": 2}]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"sort": ["id_DESC"]})

    assert len(seen) == 1, "one request, and no control request to disambiguate"
    assert "sort" not in seen[0], "the shop is never asked to do what it cannot"
    assert [row["id"] for row in result["rows"]] == [3, 2, 1]
    assert result["sorted"]["by"] == ["id_DESC"]


async def test_a_limit_is_applied_after_ordering_not_before(shop_cfg):
    """The trap that makes the naive version worse than no sort at all. Rows
    arrive id-ascending, so asking the shop for five and ordering those five
    descending answers "the newest of the oldest five" — right-looking and
    wrong. The five most recent of twenty is the whole question."""

    def handler(request):
        params = dict(request.url.params)
        assert "limit" not in params, "the caller's limit must not reach the shop"
        return httpx.Response(200, json={"orders": [{"id": i} for i in range(1, 21)]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"sort": ["id_DESC"], "limit": 5})

    assert [row["id"] for row in result["rows"]] == [20, 19, 18, 17, 16]
    assert result["total"] == 20, "the count is genuine: we held the whole set"
    assert result["complete"] is False
    assert result["sorted"]["over_rows"] == 20


async def test_ordering_by_an_undisplayed_column_asks_for_it(shop_cfg):
    """You cannot rank by a column you did not request: it comes back absent,
    every key compares equal, and the result looks sorted."""
    asked = []

    def handler(request):
        asked.append(dict(request.url.params).get("display"))
        return httpx.Response(
            200,
            json={"orders": [{"id": 1, "date_add": "2026-07-30 09:00:00"}]},
        )

    async with _http(handler, shop_cfg) as http:
        await shop.get(http, "orders", {"display": ["id"], "sort": ["date_add_DESC"]})

    assert "date_add" in asked[0]


async def test_ordering_by_a_field_no_row_has_is_refused(shop_cfg):
    """Rather than returning the rows in arbitrary order under a `sorted` label,
    which would be the same silent lie in a new place."""

    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": 1}, {"id": 2}]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"sort": ["nonesuch_DESC"]})

    assert "cannot sort by" in result["error"]
    assert "rows" not in result


async def test_an_unreadable_sort_term_says_how_to_write_one(shop_cfg):
    """A tool that cannot say "I did not understand you" is this project's
    recurring defect; a sort term is a place it would be easy to reintroduce."""

    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": 1}]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"sort": ["id"]})

    assert "FIELD_DESC" in result["error"]


async def test_numbers_sort_as_numbers_and_blanks_go_last(shop_cfg):
    """Ids arrive as strings, so "10" sorts before "9" as text, and a column
    mixing a date with an empty string cannot be compared at all."""

    def handler(request):
        return httpx.Response(
            200,
            json={"orders": [{"id": "9"}, {"id": "10"}, {"id": ""}, {"id": "2"}]},
        )

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"sort": ["id_ASC"]})

    assert [row["id"] for row in result["rows"]] == ["2", "9", "10", ""]


async def test_a_genuinely_empty_result_is_not_called_an_error(shop_cfg):
    """If the control request is also empty, nothing matched — and crying wolf
    here would make the guard useless."""

    def handler(request):
        return httpx.Response(200, json={"countries": []})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "countries", {"sort": ["id_DESC"]})

    assert result["total"] == 0
    assert "error" not in result


async def test_an_unsorted_read_is_still_one_request(shop_cfg):
    """Nothing above may cost an extra round trip on the ordinary path."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"orders": []})

    async with _http(handler, shop_cfg) as http:
        await shop.get(http, "orders", {"limit": 5})

    assert len(calls) == 1


async def test_a_read_we_truncated_declares_itself_incomplete(shop_cfg):
    """We did the cutting, so the real count IS known and `total` may be stated."""
    rows = [{"id": i} for i in range(100)]

    def handler(request):
        return httpx.Response(200, json={"orders": rows})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["complete"] is False
    assert result["returned"] == shop.MAX_ROWS
    assert result["total"] == 100
    assert result["next_offset"] == shop.MAX_ROWS


async def test_an_untruncated_read_is_complete_and_counted(shop_cfg):
    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": 1}, {"id": 2}]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["complete"] is True
    assert result["total"] == 2
    assert "next_offset" not in result


async def test_a_caller_supplied_limit_makes_completeness_unknown(shop_cfg):
    """The bug the review caught: `limit=3` against 709 rows used to answer
    `total: 3`. The shop capped it server-side and does not say what it withheld,
    so any count here would be invented."""

    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": i} for i in range(3)]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"limit": 3})

    assert result["complete"] == "unknown"
    assert result["returned"] == 3
    assert "total" not in result, "a server-capped read cannot claim a total"
    assert result["next_offset"] == 3


async def test_an_offset_limit_reports_where_the_window_started(shop_cfg):
    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": i} for i in range(25)]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", {"limit": "80,25"})

    assert result["offset"] == 80
    assert result["next_offset"] == 105
    assert result["complete"] == "unknown"


async def test_timestamps_carry_the_shop_zone(shop_cfg):
    """An order at 14:30 shop-time against a log line at 19:28 UTC reads as five
    hours of silence. The agent cannot look the zone up — `configurations` is
    refused to a read-only key."""

    def handler(request):
        return httpx.Response(
            200, json={"orders": [{"id": 1, "date_add": "2026-07-30 14:30:52"}]}
        )

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert "America/Chicago" in result["time_note"]
    assert "NOT UTC" in result["time_note"]


async def test_no_zone_note_when_no_timestamp_came_back(shop_cfg):
    """It has to appear where the trap is and nowhere else, or it is wallpaper."""

    def handler(request):
        return httpx.Response(200, json={"countries": [{"id": 1, "iso_code": "CA"}]})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "countries")

    assert "window" not in result
    assert "time_note" not in result


async def test_a_single_object_response_is_still_a_row_list(shop_cfg):
    """Asking for one id returns an object, not a list of one."""

    def handler(request):
        return httpx.Response(200, json={"order": {"id": 7}})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "order")

    assert result["rows"] == [{"id": 7}]


# ── directory and schema ─────────────────────────────────────────────────────


async def test_the_directory_reports_only_the_verbs_this_key_holds(shop_cfg):
    """The key is read-only; advertising put/post would invite a 405."""

    def handler(request):
        return httpx.Response(200, text=DIRECTORY)

    async with _http(handler, shop_cfg) as http:
        found = await shop.resources(http)

    deliveries = next(r for r in found if r["resource"] == "deliveries")
    assert deliveries["methods"] == ["get", "head"]
    assert deliveries["about"] == "Product delivery"
    assert [r["resource"] for r in found] == ["deliveries", "orders"], "sorted"


async def test_schema_exposes_the_foreign_key_the_join_depends_on(shop_cfg):
    """`id_zone` is the only route from a delivery row to a market."""

    def handler(request):
        return httpx.Response(200, text=BLANK_SCHEMA)

    async with _http(handler, shop_cfg) as http:
        result = await shop.schema(http, "deliveries")

    assert result["entity"] == "delivery"
    assert result["fields"] == ["id", "id_carrier", "id_zone", "price"]


async def test_an_unknown_resource_is_an_error_not_a_crash(shop_cfg):
    """PrestaShop answers 400, not 404, for a name it does not know."""

    def handler(request):
        return httpx.Response(400, text="<errors/>")

    async with _http(handler, shop_cfg) as http:
        result = await shop.schema(http, "nope")

    assert "no such resource" in result["error"]


async def test_a_truncated_read_points_at_the_far_end_in_one_hop(shop_cfg):
    """`orders` cannot be sorted and returns oldest-first, so recent data lives
    at the last page. `next_offset` only says "there is more"; two runs paged
    forward a little, saw nothing recent, and concluded orders had stopped —
    one of them inventing replica lag to explain it."""
    rows = [{"id": i} for i in range(138)]

    def handler(request):
        return httpx.Response(200, json={"orders": rows})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["next_offset"] == shop.MAX_ROWS
    assert result["last_offset"] == 125, "125 is where the final page starts"


async def test_no_last_offset_when_nothing_was_truncated(shop_cfg):
    def handler(request):
        return httpx.Response(200, json={"orders": [{"id": 1}]})

    async with _http(handler, shop_cfg) as http:
        assert "last_offset" not in await shop.get(http, "orders")


async def test_a_dated_read_reports_the_span_it_covers(shop_cfg):
    """A window reading 10:03–10:53 against a 15:53 clock is visibly stale.
    Without it, staleness has to be inferred from ids, and it was inferred
    wrongly twice."""
    rows = [
        {"id": 1, "date_add": "2026-07-30 10:03:55"},
        {"id": 2, "date_add": "2026-07-30 10:53:01"},
    ]

    def handler(request):
        return httpx.Response(200, json={"orders": rows})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders")

    assert result["window"] == {
        "field": "date_add",
        "first": "2026-07-30 10:03:55",
        "last": "2026-07-30 10:53:01",
    }
    assert "America/Chicago" in result["time_note"]


async def test_no_window_without_timestamps(shop_cfg):
    def handler(request):
        return httpx.Response(200, json={"countries": [{"id": 1}]})

    async with _http(handler, shop_cfg) as http:
        assert "window" not in await shop.get(http, "countries")


async def test_a_dataset_holds_the_whole_result_not_the_displayed_page(
    shop_cfg, tmp_path, monkeypatch
):
    """The first wiring saved `result["rows"]` — the 25 shown — so a join against
    it returned nothing while looking like it had worked. A dataset that silently
    holds the first page is worse than no dataset."""
    from roles.angel.tools import data

    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    rows = [{"id": i} for i in range(300)]

    def handler(request):
        return httpx.Response(200, json={"orders": rows})

    async with _http(handler, shop_cfg) as http:
        result = await shop.get(http, "orders", into="orders")

    assert len(result["rows"]) == shop.MAX_ROWS
    assert result["dataset"]["rows"] == 300, "the dataset holds everything"
    assert len(data.load("orders")) == 300


def test_an_offset_without_a_limit_still_starts_where_it_was_asked_to():
    """The shop's only paging syntax is `limit=OFFSET,COUNT`, so an offset alone
    produced no `limit` at all — and the offset is read back out of exactly that
    string. The read began at row zero while the envelope reported `offset: 0`:
    honest about what it gave, silent about ignoring what was asked. A caller
    following `next_offset` without repeating `limit` re-read page one forever,
    and every page agreed with the last."""
    params = shop.query_params(offset=100)

    assert params["limit"] == f"100,{shop.MAX_ROWS}"
    assert shop._requested_window(params) == (100, True)


def test_a_limit_and_an_offset_together_are_unchanged():
    assert shop.query_params(limit=25, offset=100)["limit"] == "100,25"
    assert shop.query_params(limit=25)["limit"] == "25"


def test_no_paging_asked_for_means_no_limit_on_the_wire():
    assert "limit" not in shop.query_params()
