"""The analytics tool against a fake Matomo.

Matomo's dangerous behaviour is that it reports failure with **HTTP 200** and a
`{"result": "error"}` body. A healthy stack almost never produces one, so the
live suite cannot cover it — and it is precisely the shape that, in PrestaShop's
equivalent, let a run mistake "I refused your query" for "there is no data" and
invent a root cause to explain it.
"""

import httpx
import pytest

from roles.angel.tools import analytics
from tests.angel.conftest import json_route, transport


def _http(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://tracking.test", transport=transport(handler)
    )


async def test_an_error_delivered_with_http_200_is_an_error(matomo_cfg):
    """The whole reason this file exists."""
    handler = json_route(
        {"result": "error", "message": "The period 'decade' is not supported"}
    )

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "VisitsSummary.get")

    assert "decade" in result["error"]
    assert "rows" not in result and "data" not in result


async def test_matomos_own_wording_survives_intact(matomo_cfg):
    """Its messages list the accepted values; paraphrasing would throw away the
    only place they are written down."""
    message = "Try any of the following instead: day, week, month, year, range"
    handler = json_route({"result": "error", "message": message})

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "VisitsSummary.get")

    assert result["error"] == message


async def test_a_4xx_says_which_status_and_where_to_look(matomo_cfg):
    handler = json_route({"nope": True}, status=404)

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "Nonsense.doesNotExist")

    assert result["error"] == "HTTP 404"
    assert "analytics_reports" in result["hint"]


async def test_a_non_json_body_does_not_raise(matomo_cfg):
    """A PHP fatal renders as HTML. Raising here would kill the investigation
    instead of letting the agent try something else."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<b>Fatal error</b>")

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "VisitsSummary.get")

    assert result["error"] == "not JSON"
    assert "Fatal" in result["body"]


async def test_a_row_report_is_labelled_rows(matomo_cfg):
    handler = json_route([{"label": "United States", "nb_visits": 9}])

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "UserCountry.getCountry")

    assert result["shape"] == "rows"
    assert result["complete"] is True
    assert result["total"] == 1
    assert result["rows"][0]["label"] == "United States"


async def test_a_metrics_report_keeps_its_dict_shape(matomo_cfg):
    """VisitsSummary.get is one dict, not a row list. Forcing it into a list
    would lose the distinction between "one summary" and "one row"."""
    handler = json_route({"nb_visits": 13, "nb_actions": 116})

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "VisitsSummary.get")

    assert result["shape"] == "metrics"
    assert result["data"]["nb_visits"] == 13


async def test_a_long_report_is_bounded_and_counted(matomo_cfg):
    handler = json_route([{"label": f"c{i}"} for i in range(80)])

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "UserCountry.getCountry")

    assert result["complete"] is False
    assert result["total"] == 80
    assert result["returned"] == analytics.MAX_ROWS
    assert result["next_offset"] == analytics.MAX_ROWS


async def test_a_caller_supplied_filter_limit_makes_completeness_unknown(matomo_cfg):
    """Matomo capped it and does not report what it withheld."""
    handler = json_route([{"label": f"c{i}"} for i in range(5)])

    async with _http(handler) as http:
        result = await analytics.get(
            http, matomo_cfg, "UserCountry.getCountry", {"filter_limit": 5}
        )

    assert result["complete"] == "unknown"
    assert "total" not in result


async def test_filter_limit_minus_one_means_everything(matomo_cfg):
    """Matomo's own idiom for "no cap" — treating it as a cap would report
    `unknown` for the one call that is provably complete."""
    handler = json_route([{"label": "a"}])

    async with _http(handler) as http:
        result = await analytics.get(
            http, matomo_cfg, "UserCountry.getCountry", {"filter_limit": -1}
        )

    assert result["complete"] is True
    assert result["total"] == 1


async def test_filter_offset_is_carried_into_the_envelope(matomo_cfg):
    handler = json_route([{"label": f"c{i}"} for i in range(5)])

    async with _http(handler) as http:
        result = await analytics.get(
            http,
            matomo_cfg,
            "UserCountry.getCountry",
            {"filter_limit": 5, "filter_offset": 100},
        )

    assert result["offset"] == 100
    assert result["next_offset"] == 105


async def test_an_omitted_server_limit_is_complete_when_everything_fits(matomo_cfg):
    handler = json_route([{"label": "a"}])

    async with _http(handler) as http:
        result = await analytics.get(http, matomo_cfg, "UserCountry.getCountry")

    assert result["complete"] is True
    assert result["total"] == 1


async def test_params_reach_matomo_as_strings(matomo_cfg):
    """A model sends {"filter_limit": 50}; httpx will not encode a bare int."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    async with _http(handler) as http:
        await analytics.get(
            http,
            matomo_cfg,
            "UserCountry.getCountry",
            {"filter_limit": 50, "period": "day"},
        )

    assert seen["filter_limit"] == "50"
    assert seen["period"] == "day"


async def test_the_token_is_posted_never_put_in_the_url(matomo_cfg):
    """Matomo 5 refuses a token in the query string, and a token in a URL leaks
    into every access log it passes through."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json=[])

    async with _http(handler) as http:
        await analytics.get(http, matomo_cfg, "UserCountry.getCountry")

    assert "token_auth" not in str(captured["url"])
    assert "token_auth=t" in str(captured["body"])


async def test_the_report_directory_is_reduced_to_what_is_callable(matomo_cfg):
    """Matomo's metadata carries documentation, image URLs and more. What an
    agent needs is the method name, what it breaks down by, and its metrics."""
    handler = json_route(
        [
            {
                "module": "UserCountry",
                "action": "getCountry",
                "name": "Country",
                "category": "Visitors",
                "dimension": "Country",
                "metrics": {"nb_visits": "Visits", "nb_actions": "Actions"},
                "documentation": "a very long help string",
                "imageGraphUrl": "…",
            }
        ]
    )

    async with _http(handler) as http:
        reports = await analytics.reports(http, matomo_cfg)

    assert reports == [
        {
            "method": "UserCountry.getCountry",
            "name": "Country",
            "category": "Visitors",
            "dimension": "Country",
            "metrics": ["nb_actions", "nb_visits"],
        }
    ]


async def test_a_broken_directory_surfaces_instead_of_looking_empty(matomo_cfg):
    """An empty catalogue would read as "this system has no reports", which is a
    very different conclusion from "the catalogue call failed"."""
    handler = json_route({"result": "error", "message": "token is bad"})

    async with _http(handler) as http:
        reports = await analytics.reports(http, matomo_cfg)

    assert reports == {"error": "token is bad"}


@pytest.mark.parametrize("payload", [{}, "", 0])
async def test_a_directory_of_the_wrong_type_is_empty_not_a_crash(matomo_cfg, payload):
    async with _http(json_route(payload)) as http:
        assert await analytics.reports(http, matomo_cfg) == []
