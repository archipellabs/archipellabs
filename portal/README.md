# Archipel Labs Simulator

Read-only web portal over the simulator's activity database — journey analytics
and a live cartography of the simulated stack. FastAPI backend (`backend/`) +
React/Vite frontend (`frontend/`).

**Prereq:** the activity DB must be reachable — `simulatordb` on `localhost:5432`
(brought up by `workspaces/default`; the same Postgres the customer-journey flow
writes to).

## Backend — `backend/` (FastAPI)

```sh
cd backend
uv sync
uv run uvicorn app.main:app --reload      # → http://localhost:8000
```

Endpoints: `GET /api/{health,analytics,cartography}`. Interactive docs at `/docs`.

## Frontend — `frontend/` (React + Vite)

```sh
cd frontend
npm install
npm run dev             # → http://localhost:5173  (proxies /api to :8000)
```

Self-contained: a small local UI kit (`src/ui/`, tokens + a few components lifted
from the corp design system) and system fonts — no external `@archipellabs/design-system`
package, no bundled webfonts.

## Docker

One multi-stage image: Node builds the SPA, then FastAPI serves the API **and**
that built bundle (same origin) on :8000.

```sh
docker build -t archipellabs-portal .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql+psycopg://simulator:changeme_demo@simulatordb:5432/simulator \
  archipellabs-portal
```

`DATABASE_URL` points at the activity DB: `@simulatordb:5432` inside the workspace
stack, or `@host.docker.internal:5432` for a standalone container on the host.

The portal serves the SPA, `/api`, and its assets at the **root** — no sub-path. In
the workspace stack the gateway publishes it on its own TLS port,
**https://localhost:8443**
([`config/gateway/nginx.conf`](../workspaces/default/config/gateway/nginx.conf)); in
production that's a subdomain. It reads the DB DSN from the shared `SIMULATORDB_URL`.
