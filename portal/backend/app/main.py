"""Archipel Labs simulator portal — read-only analytics API + the built SPA.

Everything (the /api routes, the static bundle, the SPA) is served at the root. The
gateway exposes the portal on its own port (a subdomain in production), so there is
no sub-path to carry. In local dev ./static is absent — Vite serves the SPA and
proxies /api here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncConnection

from app.cartography import catalog
from app.db import engine, get_connection
from app.queries import get_analytics
from app.schemas import Analytics

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(title="Archipel Labs Simulator", version="0.1.0", lifespan=lifespan)

Conn = Annotated[AsyncConnection, Depends(get_connection)]

api = APIRouter(prefix="/api")


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/analytics", response_model=Analytics)
async def analytics(conn: Conn) -> Analytics:
    return await get_analytics(conn)


@api.get("/cartography")
async def cartography() -> dict:
    return await catalog()


app.include_router(api)


# --- built SPA (Docker) served at the root ----------------------------------
# Registered after the API routes so they always match first. Absent in local dev,
# where Vite serves the SPA and proxies /api here.
if STATIC_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets"),
        name="assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        # A real file (favicon, etc.) is served as-is; every other path falls back
        # to index.html so the client-side router owns it. The candidate is resolved
        # and confined to STATIC_DIR so an encoded "../" can't escape the bundle.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
