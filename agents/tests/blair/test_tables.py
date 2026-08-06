import json

import pytest

from roles.blair.tools import tables, workspace


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)


def test_receipt_has_shape_provenance_and_completeness():
    result = tables.save(
        "events",
        [{"id": 1, "kind": "start"}, {"id": 2, "kind": "finish"}],
        source="system:events",
        complete="unknown",
    )

    assert result == {
        "table": "events",
        "row_count": 2,
        "fields": ["id", "kind"],
        "complete": "unknown",
        "source": "system:events",
    }


def test_rows_and_metadata_stay_on_disk():
    tables.save("events", [{"id": 1}], source="x")
    payload = json.loads((workspace.tables() / "events.json").read_text())

    assert payload["rows"] == [{"id": 1}]
    assert payload["meta"]["source"] == "x"


def test_sample_is_bounded_and_selects_fields():
    tables.save("rows", [{"id": n, "noise": "x"} for n in range(100)], source="x")

    result = tables.sample("rows", ["id"], limit=10_000)

    assert result["returned"] == tables.MAX_SAMPLE
    assert result["total"] == 100
    assert "noise" not in result["rows"][0]


def test_filter_compares_numbers_as_numbers():
    tables.save("rows", [{"n": "100"}, {"n": "5"}], source="x")

    tables.filter_rows("rows", ["n>9"], "large")

    assert tables.load("large") == [{"n": "100"}]


def test_join_never_matches_null_keys():
    tables.save("left", [{"id": 1, "k": None}, {"id": 2, "k": "x"}], source="x")
    tables.save("right", [{"id": 3, "k": None}, {"id": 4, "k": "x"}], source="y")

    result = tables.join("left", "right", "k", "k", "joined")

    assert result["matched_left_rows"] == 1
    assert tables.load("joined")[0]["id"] == 2


def test_join_propagates_uncertain_source():
    tables.save("left", [{"k": 1}], source="x", complete="unknown")
    tables.save("right", [{"k": 1}], source="y", complete=True)

    result = tables.join("left", "right", "k", "k", "joined")

    assert result["complete"] == "unknown"


def test_group_orders_numeric_measures_and_gets_numeric_extrema_right():
    rows = [{"g": "few", "v": "2"}] * 9 + [{"g": "many", "v": "10"}] * 100
    tables.save("rows", rows, source="x")

    result = tables.group("rows", ["g"], ["count", "min:v", "max:v"])

    assert result["rows"][0]["g"] == "many"
    assert result["rows"][0]["min:v"] == 10.0
    assert result["table_complete"] is True


def test_compare_puts_changed_groups_before_steady_ones():
    tables.save("before", [{"g": f"g{n}"} for n in range(50)], source="x")
    tables.save(
        "after",
        [{"g": f"g{n}"} for n in range(50)] + [{"g": "g49"}],
        source="x",
    )

    result = tables.compare("before", "after", ["g"])

    assert result["rows"][0]["g"] == "g49"
    assert result["rows"][0]["delta:count"] == 1
    assert result["left_complete"] is True
    assert result["right_complete"] is True


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", ".hidden", ""])
def test_table_names_cannot_escape(name):
    assert "error" in tables.save(name, [], source="x")
