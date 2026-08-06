"""One scratch directory per investigation.

The leak this closes is not untidiness. Datasets and downloaded logs were shared,
so a run opened with the previous run's files listed to it under names like
`affected_addresses` and `complaint_carts` — which are the previous
investigator's hypotheses stated as nouns, handed to the next one for free.

Two runs of a campaign were therefore not independent, and a rate built from them
measured something other than what it claimed.
"""

import pathlib

import httpx
import pytest

from core.config import (
    Config,
    FeedConfig,
    LokiConfig,
    MatomoConfig,
    ModelConfig,
    QueueConfig,
    ShopConfig,
)
from roles.angel.agent import deps
from roles.angel.tools import data, logs, workspace
from tests.angel.conftest import transport


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "ROOT", tmp_path)
    # The fallbacks, for the no-run case exercised below.
    monkeypatch.setattr(data, "DATA_DIR", tmp_path / "shared-datasets")
    monkeypatch.setattr(logs, "LOG_DIR", tmp_path / "shared-logs")
    return tmp_path


def test_one_run_cannot_see_another_run_s_datasets():
    token = workspace.use("i_first")
    data.save("complaint_carts", [{"id": 1}])
    workspace.release(token)

    token = workspace.use("i_second")
    try:
        assert data.load("complaint_carts") is None
    finally:
        workspace.release(token)


def test_the_same_name_in_two_runs_is_two_datasets():
    """Not merely hidden — a second run writing the same name must not overwrite
    the first, or a campaign's runs corrupt each other as well as leak."""
    token = workspace.use("i_first")
    data.save("carts", [{"id": 1}])
    workspace.release(token)

    token = workspace.use("i_second")
    data.save("carts", [{"id": 2}, {"id": 3}])
    workspace.release(token)

    token = workspace.use("i_first")
    try:
        assert [row["id"] for row in data.load("carts")] == [1]
    finally:
        workspace.release(token)


async def test_downloaded_logs_are_scoped_to_the_run_too(root):

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"result": [{"values": [["1785531600000000000", "hello"]]}]}},
        )

    http = httpx.AsyncClient(base_url="https://loki.test", transport=transport(handler))
    token = workspace.use("i_first")
    async with http:
        await logs.fetch(http, "camel", 10)
    workspace.release(token)

    token = workspace.use("i_second")
    try:
        assert not (root / "i_second" / "logs").exists()
    finally:
        workspace.release(token)


def test_outside_a_run_the_shared_directory_is_used():
    """An interactive `uv run python -m src` and every unit test land here.
    Isolation is a property of a campaign, not a reason to make a developer hunt
    for the file they just downloaded."""
    assert workspace.current() is None

    data.save("scratch", [{"id": 1}])

    assert (data.DATA_DIR / "scratch.json").is_file()


async def test_the_scratch_is_bound_to_the_run_and_released_with_its_clients():
    """The seam the shared loop hands over: one context manager opens this
    employee's clients and binds its scratch, and closing it releases both.

    It used to be a `try/finally` one layer up and an `async with` one layer
    down — two places to forget, and the reason a run's directory outlived it.
    """
    workdir = pathlib.Path("/runs/angel_abc123/workspace")

    async with deps(_config(), workdir) as opened:
        assert workspace.current() == "angel_abc123"
        assert opened.shop_http is not None

    assert workspace.current() is None


def _config() -> Config:
    """Points nowhere. Opening an httpx client connects to nothing."""
    return Config(
        model=ModelConfig(name="m", base_url="http://nowhere/v1", api_key="k"),
        shop=ShopConfig(base_url="http://nowhere", api_key="k", timezone="UTC"),
        matomo=MatomoConfig(base_url="http://nowhere", token="t", site_id="1"),
        loki=LokiConfig(base_url="http://nowhere"),
        queue=QueueConfig(url="redis://nowhere", namespace="test"),
        feed=FeedConfig(host="h", port=22, user="u", password="p", directory="/d"),
    )


def test_a_run_id_never_escapes_its_directory():
    token = workspace.use("../../etc")
    try:
        target = workspace.datasets()
        assert target is not None
        assert target.resolve().is_relative_to(workspace.ROOT.resolve())
    finally:
        workspace.release(token)
