import httpx
import pytest

from roles.blair.tools import logs, workspace
from tests.blair.conftest import transport


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)


def _loki(current, previous=None) -> httpx.AsyncClient:
    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path.endswith("/label/service/values"):
            return httpx.Response(200, json={"data": ["app"]})
        values = (
            current
            if calls % 2 == 0
            else (previous if previous is not None else current)
        )
        calls += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "result": [
                        {
                            "values": [
                                [str(1_785_534_000_000_000_000 + n), line]
                                for n, line in enumerate(values)
                            ]
                        }
                    ]
                }
            },
        )

    return httpx.AsyncClient(
        base_url="https://logs.test", transport=transport(handler)
    )


async def test_overview_exposes_change_counts_not_the_new_lines():
    http = _loki(["new operation delete"], ["old operation update"])
    async with http:
        result = await logs.overview(http, minutes=10)

    service = result["services"][0]
    assert service["new_templates"] == 1
    assert service["gone_templates"] == 1
    assert "new operation delete" not in str(result)


async def test_search_returns_bounded_matches_and_a_local_file(monkeypatch):
    monkeypatch.setattr(logs, "MAX_MATCHES", 3)
    http = _loki([f"line {n} ERROR" for n in range(10)])
    async with http:
        result = await logs.search(http, "app", pattern="error")

    assert result["matches"] == 10
    assert result["shown"] == 3
    assert result["lines"][0]["line_no"] == 1
    assert (workspace.logs() / result["file"]).is_file()


async def test_empty_search_shows_the_most_recent_lines(monkeypatch):
    monkeypatch.setattr(logs, "MAX_MATCHES", 2)
    http = _loki(["first", "second", "third"])
    async with http:
        result = await logs.search(http, "app")

    assert [row["line"].split()[-1] for row in result["lines"]] == ["second", "third"]


async def test_context_reads_around_a_match():
    http = _loki([f"line {n}" for n in range(10)])
    async with http:
        result = await logs.search(http, "app", pattern="line 5")

    around = logs.context(result["file"], result["lines"][0]["line_no"], 1, 1)
    assert len(around["lines"]) == 3


def test_context_cannot_escape_the_workspace():
    assert "error" in logs.context("../../etc/passwd", 1)


async def test_context_is_bounded_even_when_only_before_is_large():
    http = _loki([f"line {n}" for n in range(50)])
    async with http:
        result = await logs.search(http, "app", pattern="line 30")

    around = logs.context(result["file"], result["lines"][0]["line_no"], 100, 0)
    assert len(around["lines"]) <= logs.MAX_CONTEXT


def test_template_normalizes_values_but_preserves_http_status_class():
    shaped = logs._template('GET /x?id=123&token=abc HTTP/1.1" 500 42')

    assert "id=<value>" in shaped
    assert "token=<value>" in shaped
    assert "<http_5xx>" in shaped
