# syntax=docker/dockerfile:1

# Simulator image — Python 3.14 + uv + Playwright/Chromium.
#
# Heavy by nature: it bundles Chromium and its system libraries so the
# customer-journey pool can drive a real browser. It runs the runtime App; which
# flows are active is decided at runtime by the *_ENABLED flags
# (JOURNEY_ENABLED / CATALOG_ENABLED / ARRIVALS_ENABLED), not baked in.

FROM python:3.14-slim

# uv: reproducible installs straight from uv.lock. Pinned by digest (resolve a
# newer one with `docker pull ghcr.io/astral-sh/uv:latest`) for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=python3.14 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Dependencies — cached unless the lock or the local client package changes.
#    `generated/` is an editable path dependency (prestashop-clients): it must be
#    present at sync time and must stay in the image (the editable install points
#    back at it).
COPY pyproject.toml uv.lock .python-version ./
COPY generated/ ./generated/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 2) Chromium + its OS libraries (the bulk of the image). Cached unless the
#    Playwright version changes.
RUN /opt/venv/bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# 3) Application code + the PIM data the catalog flow reads at runtime.
COPY src/ ./src/
COPY data/ ./data/

# 4) Alembic config + migrations for the activity DB. Shipped so a containerised
# deploy can bring the schema up to date (the `simulator-migrate` one-off service
# runs `alembic upgrade head`); locally the developer runs alembic on the host.
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Container defaults — override per-deployment (compose env / -e).
#  - Chromium must run with --no-sandbox inside a container (BROWSER_NO_SANDBOX).
#  - Point at the compose service names; secrets (API keys) come from env/.env,
#    never baked into the image.
ENV HEADLESS=true \
    BROWSER_NO_SANDBOX=true \
    REDIS_URL=redis://redis:6379/0 \
    SHOP_BASE_URL=https://gateway

# App.start() blocks until stopped.
CMD ["/opt/venv/bin/python", "-m", "src.app"]
