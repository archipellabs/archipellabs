"""The door on the two pages that are not read-only.

These are the first tests in this package, and they are here rather than
elsewhere because auth is the one part of the portal whose failure is silent: a
guard that never guards serves every request exactly as it did before, and looks
right in a browser.

Each test drives the real app through `ASGITransport` — no route is stubbed, so a
guard removed from a decorator fails these rather than passing them.
"""

import httpx
import pytest

from app import auth
from app.config import settings
from app.main import app

PASSWORD = "a-test-password"

GUARDED = [
    ("POST", "/api/ask", {"agent": "mock", "question": "hello"}),
    ("GET", "/api/ask/whatever/events", None),
    ("GET", "/api/settings", None),
    ("POST", "/api/settings", {"key": "fast", "value": True}),
]
"""Every route that must refuse a stranger.

Listed rather than discovered, so that adding a route to the API and forgetting
to guard it does not silently add a passing case here too."""


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://portal"
    )


@pytest.fixture
def password(monkeypatch: pytest.MonkeyPatch) -> str:
    """A configured portal, with sessions signed by a key of this test's own."""
    monkeypatch.setattr(settings, "portal_password", PASSWORD)
    monkeypatch.setattr(settings, "session_secret", "test-signing-key")
    return PASSWORD


@pytest.fixture
def no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "portal_password", "")


@pytest.mark.parametrize(("method", "path", "body"), GUARDED)
async def test_guarded_routes_refuse_without_a_session(
    client: httpx.AsyncClient, password: str, method: str, path: str, body: dict | None
) -> None:
    async with client as http:
        response = await http.request(method, path, json=body)
    assert response.status_code == 401, f"{method} {path} let a stranger through"


@pytest.mark.parametrize(("method", "path", "body"), GUARDED)
async def test_guarded_routes_are_closed_when_no_password_is_set(
    client: httpx.AsyncClient, no_password: None, method: str, path: str, body: dict | None
) -> None:
    """Fail closed: an unconfigured portal shuts these rather than opening them."""
    async with client as http:
        response = await http.request(method, path, json=body)
    assert response.status_code == 503, f"{method} {path} was open with no password set"


async def test_public_routes_stay_public(client: httpx.AsyncClient, password: str) -> None:
    """The read-only window is not behind the door."""
    async with client as http:
        assert (await http.get("/api/health")).status_code == 200
        assert (await http.get("/api/agents")).status_code == 200
        assert (await http.get("/api/session")).status_code == 200


async def test_login_rejects_a_wrong_password(client: httpx.AsyncClient, password: str) -> None:
    async with client as http:
        response = await http.post("/api/login", json={"password": "not-it"})
    assert response.status_code == 401
    assert auth.COOKIE not in response.cookies


async def test_login_then_reach_a_guarded_route(client: httpx.AsyncClient, password: str) -> None:
    """The cookie the login sets is the one the guard accepts."""
    async with client as http:
        signed_in = await http.post("/api/login", json={"password": password})
        assert signed_in.status_code == 200
        assert signed_in.json() == {"signed_in": True, "configured": True}
        # The client keeps the cookie, so this is the browser's next request.
        assert (await http.get("/api/session")).json()["signed_in"] is True
        # 502, not 401: past the guard, and failing only because no simulator is
        # listening on the bus in a unit test. Asserting "not 401" would pass if
        # the route vanished, so the reached-it evidence is the specific code.
        assert (await http.get("/api/settings")).status_code == 502


async def test_logout_closes_the_session(client: httpx.AsyncClient, password: str) -> None:
    async with client as http:
        await http.post("/api/login", json={"password": password})
        await http.post("/api/logout")
        assert (await http.get("/api/session")).json()["signed_in"] is False
        assert (await http.get("/api/settings")).status_code == 401


async def test_session_reports_an_unconfigured_portal(
    client: httpx.AsyncClient, no_password: None
) -> None:
    """So the page can say *nobody set a password* rather than *sign in*."""
    async with client as http:
        assert (await http.get("/api/session")).json() == {
            "signed_in": False,
            "configured": False,
        }


async def test_login_refuses_when_no_password_is_configured(
    client: httpx.AsyncClient, no_password: None
) -> None:
    """A blank password must not be satisfiable by a blank guess."""
    async with client as http:
        assert (await http.post("/api/login", json={"password": " "})).status_code == 503


def test_a_tampered_cookie_is_rejected(password: str) -> None:
    """The expiry is signed, so pushing it into the future invalidates it."""
    good = auth._sign(2_000_000_000)
    assert auth.valid(good)
    stamp, _, mac = good.partition(".")
    assert not auth.valid(f"{int(stamp) + 3600}.{mac}"), "a rewritten expiry was accepted"
    assert not auth.valid(f"{stamp}.{'0' * len(mac)}")
    assert not auth.valid("nonsense")
    assert not auth.valid(None)


def test_an_expired_cookie_is_rejected(password: str) -> None:
    """Correctly signed and out of date is still out."""
    assert not auth.valid(auth._sign(1_000_000_000))


def test_a_cookie_signed_with_another_key_is_rejected(
    password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotating the secret signs everyone out, which is what a rotation is for."""
    theirs = auth._sign(2_000_000_000)
    monkeypatch.setattr(settings, "session_secret", "a-different-key")
    assert not auth.valid(theirs)
