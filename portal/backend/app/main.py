"""Archipel Labs simulator portal — read-only analytics API + the built SPA.

Everything (the /api routes, the static bundle, the SPA) is served at the root. The
gateway exposes the portal on its own port (a subdomain in production), so there is
no sub-path to carry. In local dev ./static is absent — Vite serves the SPA and
proxies /api here.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncConnection

from app import auth
from app.bus import AGENTS, Bus, Busy, requests, settled, stream
from app.cartography import catalog
from app.config import settings
from app.db import engine, get_connection
from app.queries import get_analytics
from app.schemas import Analytics, Ask, Asked, Login, SettingChange
from app.schemas import Session as SessionState

log = logging.getLogger("portal")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SILENT_AFTER = 90.0
"""Seconds an analyst may say nothing before this process stops holding its name.

Not a run deadline — an investigation takes minutes and is left alone. This is
the *pick-up* deadline, and the two are different questions: a working analyst
announces itself almost immediately, so the only reasons for silence are that
nobody is serving that name or that another caller's ticket is ahead of it on
the bus. Either way the portal's own lock is doing no good.

Generous, because one employee was once observed taking about two minutes to
take a ticket and the cause was never pinned down. Declaring a live analyst dead
is the worse mistake of the two: it invites a second ticket onto a queue that is
already moving."""


bus = Bus(settings.redis_url, settings.redis_namespace)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # The bus is opened once for the process, never per request: a subscriber
    # holds a Redis connection budget sized to its slots, and one App per request
    # would find that ceiling as a crash rather than as a misconfiguration.
    #
    # A portal that cannot reach the bus still serves its read-only pages, so a
    # failure here is logged and survived rather than fatal. The ask page will
    # say the employees are unreachable, which is true and better than a blank
    # site.
    try:
        await bus.start()
    except Exception:  # noqa: BLE001 - the rest of the portal does not need it
        log.exception("the agent bus is unreachable; /api/ask will refuse")
    yield
    await bus.stop()
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


@api.get("/agents")
async def agents() -> dict[str, list[str]]:
    """Who can be asked, so the page never offers a door that is not there."""
    return {"agents": list(AGENTS)}


Guarded = Annotated[None, Depends(auth.require_session)]
"""Marks a route as one of the two that are not read-only."""


@api.get("/session", response_model=SessionState)
async def session(portal_session: auth.Session = None) -> SessionState:
    """Unguarded on purpose — this is how a page asks whether it needs the door."""
    # `signed_in` is true when nothing is being asked: the question the page is
    # really putting is "may I render", and with auth off the answer is yes.
    # `required` carries the distinction for anything that needs it.
    return SessionState(
        signed_in=not auth.required() or auth.valid(portal_session),
        configured=auth.configured(),
        required=auth.required(),
    )


@api.post("/login", response_model=SessionState)
async def login(request: Login, response: Response) -> SessionState:
    if not auth.configured():
        raise HTTPException(
            status_code=503,
            detail="this portal has no password configured, so protected pages are closed",
        )
    if not auth.matches(request.password):
        # No detail about which part was wrong, and no timing difference worth
        # measuring: there is one secret and the comparison is constant-time.
        raise HTTPException(status_code=401, detail="that is not the password")
    auth.issue(response)
    return SessionState(signed_in=True, configured=True, required=auth.required())


@api.post("/logout", response_model=SessionState)
async def logout(response: Response) -> SessionState:
    auth.revoke(response)
    return SessionState(
        signed_in=not auth.required(),
        configured=auth.configured(),
        required=auth.required(),
    )


@api.get("/settings")
async def read_settings(_: Guarded) -> dict:
    """What the simulator will let anyone change, and where each value comes from."""
    try:
        return await bus.describe_config()
    except Exception as error:  # noqa: BLE001 - the page is owed a reason
        log.exception("could not read the simulator's configuration")
        raise HTTPException(
            status_code=502,
            detail=f"the simulator did not answer: {type(error).__name__}: {error}",
        ) from error


@api.post("/settings")
async def write_setting(change: SettingChange, _: Guarded) -> dict:
    """Change one knob, and report the layer that now answers.

    A rejected key or a rejected value comes back from the simulator as a failed
    call, and both are the caller's fault rather than the portal's — hence 400
    rather than 502. The simulator's own message is passed through: it names the
    keys it accepts, which is exactly what somebody who mistyped one needs.
    """
    try:
        return await bus.apply_config(change.key, change.value)
    except Exception as error:  # noqa: BLE001 - the page is owed a reason
        log.warning("rejected setting %r: %s", change.key, error)
        raise HTTPException(
            status_code=400, detail=f"{type(error).__name__}: {error}"
        ) from error


@api.post("/ask", response_model=Asked)
async def ask(request: Ask, _: Guarded) -> Asked:
    """Put a question to one analyst and reserve the stream that will carry it.

    Two steps rather than one because an SSE response cannot carry a status code
    the browser can act on: `EventSource` reports every failure as the same
    opaque error. Refusing here, as a plain 409 with a sentence, is the only way
    the page can say *that one is busy, pick another* rather than *something went
    wrong*.
    """
    if request.agent not in AGENTS:
        raise HTTPException(
            status_code=404, detail=f"no analyst called {request.agent}"
        )
    try:
        reference, queue = await requests.open(request.agent)
    except Busy as busy:
        raise HTTPException(status_code=409, detail=str(busy)) from busy

    async def nobody_answered() -> None:
        """Give up on an analyst that never picked the ticket up.

        **An agent that vanishes used to hold its own name for a quarter of an
        hour.** The slot is freed when the work ends, and the work ends when the
        call returns — so a process that is simply not running leaves the call
        waiting out its full ttl, and every attempt in between is refused with
        "is already working on a question" while nothing is working at all.
        Restarting the portal was the only cure.

        The signal is the analyst's own first event. A running employee
        publishes `started` within a second or two of receiving a ticket, so
        silence past a generous deadline means nobody is serving that name.

        The call is **not** cancelled — it cannot be, and a slow-but-alive
        analyst may yet answer into a queue nobody reads, which `deliver` already
        treats as the ordinary case. What is released is this process's own lock,
        which was never the agent's to hold.
        """
        await asyncio.sleep(SILENT_AFTER)
        if requests.heard(reference):
            return
        log.warning(
            "%s said nothing in %.0fs; freeing it — is its process running?",
            request.agent,
            SILENT_AFTER,
        )
        await requests.done(request.agent, reference)
        queue.put_nowait(
            {
                "kind": "failed",
                "reason": (
                    f"{request.agent} did not answer within "
                    f"{SILENT_AFTER:.0f}s. Its process may not be running."
                ),
            }
        )
        queue.put_nowait(None)

    async def work() -> None:
        """Issue the call, and make sure the stream ends whatever happens.

        Run as a task so the HTTP request returns immediately with the reference:
        an investigation takes minutes, and a browser that has not yet opened its
        EventSource would miss the opening steps.
        """
        watchdog = asyncio.get_running_loop().create_task(nobody_answered())
        try:
            # The reply *is* the answer. The analysts' own closing events are
            # not subscribed, because neither lineage's carries a usable verdict
            # — see the note beside the subscriptions in `bus`.
            reply = await bus.ask(
                request.agent,
                request.question,
                request.model,
                request.effort,
                reference,
            )
            queue.put_nowait(settled(reply))
        except Exception as error:  # noqa: BLE001 - the reader is owed a reason
            log.exception("the call to %s failed", request.agent)
            queue.put_nowait(
                {"kind": "failed", "reason": f"{type(error).__name__}: {error}"}
            )
        finally:
            watchdog.cancel()
            # **The analyst is freed here, not when the reader leaves.** This
            # task is the only thing that knows the investigation ended. Freeing
            # it in the stream's `finally` instead meant a request that posted
            # and never opened its stream — a reload, a double submit, a closed
            # tab — held the analyst until this process restarted, and every
            # later attempt was told it "is already working on a question" while
            # nothing was working.
            await requests.done(request.agent, reference)
            # A sentinel behind the terminal event, so a reader is released even
            # if the call returned something `settled` could make nothing of.
            queue.put_nowait(None)

    asyncio.get_running_loop().create_task(work())
    return Asked(reference=reference, agent=request.agent)


@api.get("/ask/{reference}/events")
async def ask_events(reference: str, _: Guarded) -> StreamingResponse:
    """The live trace for one request, as server-sent events."""
    queue = requests.queue_for(reference)
    if queue is None:
        raise HTTPException(
            status_code=404, detail="no such request, or it has finished"
        )

    async def body() -> AsyncIterator[str]:
        agent = requests.agent_for(reference) or ""
        try:
            async for event in stream(queue):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            # Frees the analyst for the next question even when the browser
            # disappears mid-investigation, which is the common case.
            await requests.close(agent, reference)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
