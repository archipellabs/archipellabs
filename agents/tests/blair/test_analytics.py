import httpx
import pytest

from roles.blair.tools import analytics, tables, workspace
from tests.blair.conftest import transport


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)


def _http(payload) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://tracking.test",
        transport=transport(lambda request: httpx.Response(200, json=payload)),
    )


async def test_matomo_error_inside_http_200_is_an_error(matomo_cfg):
    async with _http({"result": "error", "message": "bad period"}) as http:
        result = await analytics.query(http, matomo_cfg, "VisitsSummary.get")

    assert result["error"] == "bad period"


async def test_catalog_can_be_narrowed_without_a_hard_coded_report(matomo_cfg):
    payload = [
        {
            "module": "VisitsSummary",
            "action": "get",
            "name": "Visits",
            "category": "Visitors",
            "metrics": {"nb_visits": "Visits"},
        },
        {
            "module": "DevicesDetection",
            "action": "getType",
            "name": "Device type",
            "category": "Devices",
            "dimension": "Device",
            "metrics": {},
        },
    ]
    async with _http(payload) as http:
        result = await analytics.catalog(http, matomo_cfg, search="device")

    assert result["total"] == 1
    assert result["reports"][0]["method"] == "DevicesDetection.getType"


async def test_row_report_can_be_saved_without_pasting_all_rows(matomo_cfg):
    payload = [{"label": f"v{n}", "nb_visits": n} for n in range(40)]
    async with _http(payload) as http:
        result = await analytics.query(
            http,
            matomo_cfg,
            "Example.get",
            {"filter_limit": -1},
            save_as="visits",
        )

    assert "rows" not in result
    assert len(result["preview"]) == analytics.MAX_PREVIEW
    assert result["table"]["complete"] is True
    assert len(tables.load("visits")) == 40


async def test_metrics_keep_their_native_shape(matomo_cfg):
    async with _http({"nb_visits": 12}) as http:
        result = await analytics.query(http, matomo_cfg, "VisitsSummary.get")

    assert result == {
        "method": "VisitsSummary.get",
        "shape": "metrics",
        "data": {"nb_visits": 12},
    }
