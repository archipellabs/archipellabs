"""One shared password, and a signed cookie that remembers it.

The portal is a public read-only window onto a simulated company, with two
exceptions: `/api/ask` spends real money on a model, and `/api/settings` changes
how the company behaves. Those two need a door.

**One password rather than accounts.** There is nothing here to attribute: the
lab has one operator, the settings are four knobs and a set of switches, and a
`users` table would buy an audit trail nobody reads at the cost of a migration,
a hashing choice, and an account lifecycle. When the question becomes *who
changed the arrival rate*, that is the moment to grow this — not before.

**The cookie carries an expiry and a signature, and nothing else.** There is no
session store, so nothing to evict and no state to lose on restart. The value is
`<expires-at>.<hmac>`; verification recomputes the hmac and compares in constant
time. A tampered expiry fails the signature, and a valid-but-old one fails the
clock.

**It fails closed.** With no password configured the protected routes refuse and
say so, rather than serving. An empty secret must never mean an open door — the
one failure mode worth designing against here is a deployment that forgets to
set it and never finds out.
"""

import hashlib
import hmac
import logging
import secrets
import time
from typing import Annotated

from fastapi import Cookie, HTTPException, Response

from app.config import settings

log = logging.getLogger("portal")

COOKIE = "portal_session"

MAX_AGE = 12 * 60 * 60
"""How long a session lasts, in seconds.

A working day. Long enough that an operator watching an investigation is not
logged out mid-stream, short enough that a forgotten browser is not a standing
key."""


def _secret() -> bytes:
    """The signing key, or a per-process one if the deployment named none.

    A generated key means restarting the portal invalidates every session, which
    is a mild annoyance and a safe default — the alternative, a constant baked
    into the source, is a key everyone with the repository already holds.
    """
    return settings.session_secret.encode() or _EPHEMERAL


_EPHEMERAL = secrets.token_bytes(32)


def _sign(expires_at: int) -> str:
    mac = hmac.new(_secret(), str(expires_at).encode(), hashlib.sha256).hexdigest()
    return f"{expires_at}.{mac}"


def issue(response: Response) -> None:
    """Put a fresh session cookie on the response."""
    expires_at = int(time.time()) + MAX_AGE
    response.set_cookie(
        COOKIE,
        _sign(expires_at),
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        # False by default because local development is plain http on
        # localhost, where a Secure cookie is silently dropped and the login
        # appears to succeed and do nothing. Deployments behind the gateway's
        # TLS set PORTAL_COOKIE_SECURE=true.
        secure=settings.cookie_secure,
        path="/",
    )


def revoke(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def valid(cookie: str | None) -> bool:
    """Whether this cookie was signed by us and has not expired."""
    if not cookie or "." not in cookie:
        return False
    stamp, _, mac = cookie.partition(".")
    try:
        expires_at = int(stamp)
    except ValueError:
        return False
    # Signature first, then the clock: comparing the mac on every path keeps the
    # work constant whatever the input, and a forged expiry never reaches the
    # comparison that would leak whether it was in range.
    if not hmac.compare_digest(_sign(expires_at), cookie):
        return False
    return expires_at > time.time()


def matches(password: str) -> bool:
    """Whether the offered password is the configured one.

    Constant-time, and false when nothing is configured — a blank password must
    not be satisfiable by a blank guess.
    """
    expected = settings.portal_password
    if not expected:
        return False
    return hmac.compare_digest(password.encode(), expected.encode())


def configured() -> bool:
    return bool(settings.portal_password)


def required() -> bool:
    """Whether the two guarded pages ask for anything at all.

    Off, they are open to whoever can reach the port — which on a local stack is
    the operator and nobody else. It is reported to the page rather than
    inferred, so a browser shows the pages instead of a sign-in form nothing
    would accept.
    """
    return settings.auth_enabled


Session = Annotated[str | None, Cookie(alias=COOKIE)]


async def require_session(portal_session: Session = None) -> None:
    """Guard a route. Raises 503 if no password is set, 401 if not signed in.

    The two are told apart on purpose. A 401 tells the visitor to sign in; a 503
    tells the *operator* that the deployment has no password and the route is
    therefore closed to everyone, which is a different problem with a different
    fix and would be invisible if both said "unauthorized".
    """
    if not required():
        # Said once per request at debug rather than warned: an operator who
        # turned it off does not need telling, and a log that cries wolf about a
        # deliberate setting is a log nobody reads.
        log.debug("PORTAL_AUTH_ENABLED is false; this route is open")
        return
    if not configured():
        log.warning("PORTAL_PASSWORD is not set; protected routes are closed")
        raise HTTPException(
            status_code=503,
            detail="this portal has no password configured, so protected pages are closed",
        )
    if not valid(portal_session):
        raise HTTPException(status_code=401, detail="sign in to use this page")
