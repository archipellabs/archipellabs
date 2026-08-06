"""The relational primitives: join, aggregate, compare.

These exist to remove mechanical work, and the test that matters is the question
every run struggled with — orders per country — which needs three resources,
three schemas and a two-hop join. One run spent 22 shop calls assembling it.

Nothing here knows what a carrier is. That is the line: joining and counting is
the tool's job, deciding what a missing row means is the agent's.
"""

import pytest

from roles.angel.tools import data


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)


def seed() -> None:
    data.save(
        "orders",
        [
            {"id": 1, "id_address_delivery": 10, "total": "15.00"},
            {"id": 2, "id_address_delivery": 11, "total": "25.00"},
            {"id": 3, "id_address_delivery": 10, "total": "15.00"},
        ],
    )
    data.save(
        "addresses",
        [
            {"id": 10, "id_country": 21},
            {"id": 11, "id_country": 4},
            {"id": 12, "id_country": 4},
        ],
    )
    data.save("countries", [{"id": 21, "iso_code": "US"}, {"id": 4, "iso_code": "CA"}])


def test_orders_per_country_in_three_calls():
    """The whole point of the module."""
    seed()
    data.join("orders", "addresses", "id_address_delivery", "id", "oa")
    data.join("oa", "countries", "id_country", "id", "oac")

    result = data.aggregate("oac", ["iso_code"], ["count", "sum:total"])

    rows = {r["iso_code"]: r for r in result["rows"]}
    assert rows["US"]["count"] == 2
    assert rows["US"]["sum:total"] == 30.0
    assert rows["CA"]["count"] == 1


def test_a_left_join_finds_rows_with_nothing_on_the_other_side():
    """ "Addresses that produced no order" — the shape of half the questions an
    incident asks, and impossible with an inner join."""
    seed()

    result = data.join(
        "addresses", "orders", "id", "id_address_delivery", "ao", how="left"
    )

    assert result["unmatched_left_rows"] == 1, "address 12 ordered nothing"
    assert result["matched_left_rows"] == 2


def test_colliding_fields_are_prefixed_not_overwritten():
    """Both sides have `id`. Silently overwriting it would corrupt the column
    someone is about to group by."""
    seed()

    result = data.join("orders", "addresses", "id_address_delivery", "id", "oa")

    assert "r_id" in result["fields"]
    assert data.load("oa")[0]["id"] == 1, "the left id survives"


def test_an_empty_group_by_measures_the_whole_dataset():
    seed()

    result = data.aggregate("orders", [], ["count", "sum:total"])

    assert result["rows"] == [{"count": 3, "sum:total": 55.0}]


def test_compare_reports_the_delta_between_two_windows():
    """ "What changed since the previous window" without subtracting two tables
    in your head."""
    data.save("before", [{"c": "US", "n": 1}, {"c": "CA", "n": 1}])
    data.save("after", [{"c": "US", "n": 1}, {"c": "US", "n": 1}])

    result = data.compare("before", "after", ["c"], ["count"])

    rows = {r["c"]: r for r in result["rows"]}
    assert rows["US"]["delta:count"] == 1
    assert rows["CA"]["in_left"] is True
    assert rows["CA"]["in_right"] is False, (
        "a market that vanished is the case that matters"
    )


def test_an_unusable_measure_says_what_is_allowed():
    """A silent empty column would read as "this field has no values"."""
    seed()

    result = data.aggregate("orders", ["id"], ["median:total"])

    assert "unusable measure" in result["error"]
    assert "sum:field" in result["hint"]


def test_a_missing_dataset_is_an_error_not_an_empty_result():
    assert "no such dataset" in data.aggregate("nope", ["x"])["error"]
    assert "no such dataset" in data.join("nope", "nope", "a", "b", "out")["error"]


@pytest.mark.parametrize("name", ["../escape", "/etc/passwd", "sub/dir/x"])
def test_a_dataset_name_is_confined_and_reported_truthfully(name, tmp_path):
    """Names come from the model, so the path is sanitised — and the handle must
    say what was actually written, not repeat what was asked for."""
    result = data.save(name, [{"a": 1}])

    assert "/" not in result["dataset"] and ".." not in result["dataset"]
    assert (tmp_path / f"{result['dataset']}.json").is_file()


@pytest.mark.parametrize("name", [".hidden", ""])
def test_an_unusable_dataset_name_is_refused(name):
    assert "error" in data.save(name, [{"a": 1}])


def test_measures_ignore_rows_where_the_field_is_missing():
    """A blank total is not a zero; averaging it in would quietly skew the answer."""
    data.save("mixed", [{"g": "a", "v": "10"}, {"g": "a", "v": ""}, {"g": "a"}])

    result = data.aggregate("mixed", ["g"], ["count", "avg:v"])

    assert result["rows"][0]["count"] == 3, "every row is still a row"
    assert result["rows"][0]["avg:v"] == 10.0, "but only one has a value"


# ── the defects a review of the fifteen-run campaign found ───────────────────


def test_a_join_on_a_field_nobody_has_is_refused():
    """The worst kind of wrong answer this module could give. Missing keys read
    as `None` on both sides, `None` equalled `None`, and joining two misspelled
    columns reported every row matched and none unmatched — confident, complete
    and entirely false."""
    data.save("carts", [{"id": 1, "id_addr": 7}, {"id": 2, "id_addr": 8}])
    data.save("orders", [{"id": 9, "id_cart": 1}])

    result = data.join("carts", "orders", "nope_left", "nope_right", "out")

    assert "has no field" in result["error"]
    assert "id_addr" in result["fields"], "say what the dataset does have"


def test_an_anti_join_keeps_only_what_never_matched():
    """ "Carts that never became an order" directly, rather than a left join the
    caller has to filter — and without a purpose-built abandoned-cart tool that
    would answer the incident on the agent's behalf."""
    data.save("carts", [{"id": 1}, {"id": 2}, {"id": 3}])
    data.save("orders", [{"id_cart": 2}])

    result = data.join("carts", "orders", "id", "id_cart", "orphans", how="anti")

    assert result["rows"] == 2
    assert [row["id"] for row in data.load("orphans")] == [1, 3]


def test_compare_sees_every_group_not_the_fifty_it_displays():
    """`compare` read `aggregate`'s already-capped rows, so a group past the
    fiftieth was reported as absent from one side rather than merely unshown —
    manufacturing the very "this market stopped appearing" headline it exists to
    report."""
    data.save("before", [{"country": f"c{n:03d}"} for n in range(60)])
    data.save("after", [{"country": f"c{n:03d}"} for n in range(60)])

    result = data.compare("before", "after", ["country"])

    assert result["groups"] == 60
    assert all(row["in_left"] and row["in_right"] for row in result["rows"]), (
        "nothing vanished between two identical datasets"
    )


def test_aggregates_sort_by_number_not_by_text():
    """Sorted as text, 9 outranked 100, so "the biggest groups" were whichever
    ones began with a high digit."""
    data.save("rows", [{"g": "few"}] * 9 + [{"g": "many"}] * 100)

    result = data.aggregate("rows", ["g"], ["count"])

    assert [row["g"] for row in result["rows"]] == ["many", "few"]


def test_grouping_by_a_field_nobody_has_is_refused():
    """A misspelled `group_by` silently produced one group keyed on the empty
    string, which looks like a real finding about a dataset with no variation."""
    data.save("rows", [{"country": "CA"}, {"country": "US"}])

    result = data.aggregate("rows", ["cuntry"])

    assert "has no field" in result["error"]


def test_filter_keeps_the_matching_rows_and_says_what_it_dropped():
    data.save(
        "carts",
        [
            {"id": 1, "iso": "CA", "carrier": "0"},
            {"id": 2, "iso": "US", "carrier": "3"},
            {"id": 3, "iso": "CA", "carrier": "3"},
        ],
    )

    result = data.filter_("carts", ["iso=CA", "carrier!=0"], "kept")

    assert result["rows"] == 1
    assert result["from_rows"] == 3
    assert result["removed"] == 2
    assert data.load("kept")[0]["id"] == 3


def test_filter_compares_numbers_as_numbers():
    """`total>9` must not keep `100` out because "1" sorts below "9"."""
    data.save("orders", [{"total": "100"}, {"total": "5"}])

    data.filter_("orders", ["total>9"], "big")

    assert [row["total"] for row in data.load("big")] == ["100"]


@pytest.mark.parametrize("clause", ["idcarrier", "", "="])
def test_an_unreadable_condition_says_how_to_write_one(clause):
    data.save("rows", [{"id": 1}])

    result = data.filter_("rows", [clause], "out")

    assert "hint" in result or "has no field" in result["error"]


def test_filter_refuses_a_field_the_dataset_has_never_heard_of():
    data.save("rows", [{"id": 1, "iso": "CA"}])

    result = data.filter_("rows", ["country=CA"], "out")

    assert "has no field" in result["error"]
    assert "iso" in result["fields"]


def test_sample_reads_rows_and_declares_how_many_it_did_not():
    data.save("rows", [{"id": n, "noise": "x"} for n in range(30)])

    result = data.sample("rows", fields=["id"], limit=5)

    assert [row["id"] for row in result["rows"]] == [0, 1, 2, 3, 4]
    assert result["total"] == 30
    assert result["complete"] is False
    assert "noise" not in result["rows"][0], "only the fields asked for"



def test_a_row_with_no_key_matches_nothing_rather_than_everything():
    """`str(None)` is `"None"` on both sides, so every left row missing the key
    joined to every right row missing it — a cross product of exactly the rows
    that carry no information. A cart with no delivery address and an order with
    no carrier are ordinary here, and pairing them manufactures the kind of
    correlation an investigation exists to find. SQL refuses to equate two NULLs
    for the same reason."""
    data.save("carts", [{"id": 1, "addr": None}, {"id": 2, "addr": 7}])
    data.save("addresses", [{"addr": None, "country": "?"}, {"addr": 7, "country": "CA"}])

    joined = data.join("carts", "addresses", "addr", "addr", into="both")

    assert joined["rows"] == 1, "only the row that actually has a key"
    assert joined["unmatched_left_rows"] == 1
    assert data.load("both")[0]["country"] == "CA"


def test_an_empty_string_key_is_as_absent_as_a_missing_one():
    """PrestaShop returns `""` for an unset integer reference as often as it
    returns nothing, and a join whose result depended on which one arrived would
    be a join that depended on the weather."""
    data.save("left", [{"k": ""}])
    data.save("right", [{"k": "", "flag": "x"}])

    joined = data.join("left", "right", "k", "k", into="out")

    assert joined["rows"] == 0
    assert joined["unmatched_left_rows"] == 1


def test_the_smallest_number_is_the_smallest_number():
    """`key=str` made every comparison lexicographic — it was there to stop a
    mixed column raising, and it did, by making the answer wrong instead. `min`
    over 10 and 2 compared `"10.0"` against `"2.0"` and returned 10. An analyst
    asking for the lowest stock level got the highest."""
    data.save("stock", [{"q": "10"}, {"q": "2"}, {"q": "7"}])

    measured = data.aggregate("stock", group_by=[], measures=["min:q", "max:q"])
    row = measured["rows"][0]

    assert row["min:q"] == 2.0
    assert row["max:q"] == 10.0


def test_a_date_column_still_orders_the_way_it_reads():
    """The reason the string fallback exists at all."""
    data.save("orders", [{"at": "2026-08-05"}, {"at": "2026-01-02"}])

    row = data.aggregate("orders", group_by=[], measures=["min:at"])["rows"][0]

    assert row["min:at"] == "2026-01-02"


def test_a_dataset_remembers_that_it_holds_only_part_of_the_truth():
    """The read reports `complete: "unknown"` honestly, then the rows were saved
    and the marker was not. An aggregate over that dataset counted a partial set
    and answered as though it were the whole — this package's founding lie, one
    layer further along than the layer written to retire it."""
    data.save("capped", [{"id": 1}], complete="unknown", source="shop:orders")

    handle = data.info("capped")

    assert handle["complete"] == "unknown"
    assert handle["source"] == "shop:orders"


def test_a_dataset_the_model_built_itself_claims_nothing():
    """Absent is not the same as `complete: false`. A handle that asserted
    something nobody established would be the same defect wearing a new hat."""
    data.save("mine", [{"id": 1}])

    handle = data.info("mine")

    assert "complete" not in handle and "source" not in handle


def test_a_dataset_overwritten_by_a_complete_read_stops_claiming_partial():
    """Stale provenance is worse than none: it would mark a whole table partial
    forever because one earlier read of that name was capped."""
    data.save("orders", [{"id": 1}], complete="unknown", source="shop:orders")
    data.save("orders", [{"id": 1}, {"id": 2}])

    assert "complete" not in data.info("orders")


def test_the_marker_file_is_not_itself_a_dataset():
    data.save("orders", [{"id": 1}], complete=True, source="shop:orders")

    assert [d["dataset"] for d in data.datasets()] == ["orders"]
