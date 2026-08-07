"""How the built SPA is cached.

The pair matters more than either header: `index.html` names a content-hashed
bundle, so a browser allowed to reuse yesterday's copy asks for a file this build
no longer ships and renders nothing at all. A blank page, from a server answering
correctly in under a second — which is why this is a test rather than a comment.
"""

import httpx
import pytest

from app.main import IMMUTABLE, REVALIDATE, STATIC_DIR, app


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://portal"
    )


needs_build = pytest.mark.skipif(
    not STATIC_DIR.is_dir(),
    reason="no built SPA here — it is baked into the image, not the source tree",
)


@needs_build
async def test_index_is_revalidated(client: httpx.AsyncClient) -> None:
    """Every visit asks whether it changed; a 304 makes that nearly free."""
    async with client as http:
        response = await http.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == REVALIDATE


@needs_build
async def test_a_client_route_is_revalidated_too(client: httpx.AsyncClient) -> None:
    """`/settings` is index.html wearing another name — same rule applies."""
    async with client as http:
        response = await http.get("/settings")

    assert response.status_code == 200
    assert response.headers["cache-control"] == REVALIDATE


@needs_build
async def test_hashed_assets_are_immutable(client: httpx.AsyncClient) -> None:
    """The filename is the version, so the copy can never be the wrong one."""
    assets = sorted((STATIC_DIR / "assets").glob("*.js"))
    assert assets, "the build produced no javascript bundle"

    async with client as http:
        response = await http.get(f"/assets/{assets[0].name}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_the_two_policies_disagree() -> None:
    """A guard against 'fixing' this by giving both the same value.

    Making the assets revalidate would work and cost a request per asset per
    visit; making index.html immutable would strand every browser on the build it
    first met, which is the bug this file exists for.
    """
    assert IMMUTABLE != REVALIDATE
    assert "immutable" in IMMUTABLE
    assert "no-cache" in REVALIDATE
