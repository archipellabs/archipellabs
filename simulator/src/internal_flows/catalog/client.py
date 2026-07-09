"""PrestaShop Webservice API clients (async).

Two async httpx clients share the same Basic auth: one returns JSON (reads), one
speaks XML (writes). The catalog code drives PrestaShop's Webservice with raw
requests + hand-built XML, so plain `httpx.AsyncClient`s are all it needs (the
generated client added nothing here but a configured httpx).
"""

import base64

import httpx

from src.config import settings


def _basic_auth() -> str:
    token = base64.b64encode(f"{settings.prestashop_webservice_api_key}:".encode())
    return f"Basic {token.decode()}"


def _client(extra_headers: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.prestashop_webservice_url,
        verify=False,
        headers={"Authorization": _basic_auth(), **extra_headers},
    )


def json_client() -> httpx.AsyncClient:
    """Async client for JSON reads (GET): Basic auth + `Output-Format: JSON`."""
    return _client({"Output-Format": "JSON"})


def xml_client() -> httpx.AsyncClient:
    """Async client for XML writes (POST/PUT/DELETE)."""
    return _client({"Accept": "application/xml"})
