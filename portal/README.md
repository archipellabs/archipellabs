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

Endpoints: `GET /api/{health,analytics,cartography,agents,session}`, `POST /api/{login,logout,ask}`, `GET|POST /api/settings`, and the SSE stream `GET /api/ask/{reference}/events`. Interactive docs at `/docs`.

## Frontend — `frontend/` (React + Vite)

```sh
cd frontend
npm install
npm run dev             # → http://localhost:5173  (proxies /api to :8000)
```

Self-contained: a small local UI kit (`src/ui/`, tokens + a few components lifted
from the corp design system) and system fonts — no external `@archipellabs/design-system`
package, no bundled webfonts.

## The door — `/ask` and `/settings`

Two pages are not read-only: one spends real money on a model, the other changes
how the simulated company behaves. Both ask for one shared password.

```sh
PORTAL_PASSWORD=... uv run uvicorn app.main:app --reload
```

**Unset means closed, not open.** With no password the two pages refuse everyone
and say so — the failure mode worth designing against is a deployment that
forgets the variable and never finds out.

| variable | |
|---|---|
| `PORTAL_PASSWORD` | the password. No password, no access. |
| `PORTAL_SESSION_SECRET` | signs the session cookie. Unset means a fresh key per process, so restarting signs everyone out. |
| `PORTAL_AUTH_ENABLED` | whether the two pages ask at all. **`true` by default** — a deployment that says nothing is a deployment that asks. `false` opens them without a password, for a laptop. |
| `PORTAL_COOKIE_SECURE` | send the cookie only over TLS. `false` by default because local dev is http on localhost, where a Secure cookie is dropped in silence and the login looks like it failed. |

One password rather than accounts, because there is nothing here to attribute
yet. When the question becomes *who changed the arrival rate*, that is the moment
to grow it. Sessions last twelve hours; there is no session store, so nothing to
evict — the cookie carries a signed expiry and that is all.

## Controlling the simulator — `/settings`

The knobs the simulator says may be moved while it runs, and the flows that may
be paused. Values come from `config.describe` over the bus and changes go back
through `config.apply` — **the portal never writes to the simulator's database.**
The layering (an override, then this deployment's environment, then the shipped
default) lives in the simulator's configuration service, and asking keeps that
judgement in one place instead of copying it here to drift.

Each row says where its current value came from, which is what makes the reset
button honest: *back to 3/min* and *back to whatever this deployment configured*
are different promises.

Changes reach the running simulator within about a minute — it reads settings
from a snapshot rather than the database on every tick. Nothing here restarts
anything, and a knob whose change could not take effect mid-run is deliberately
absent from the list rather than present and ignored.

## Asking an analyst — `/ask`

Put a question to one of the simulated employees and watch it work: the call goes
out on the bus, its steps stream back over SSE, and the answer arrives with what
the run spent.

**An employee only answers if its process is running.** The picker lists everyone
the bus can route to, which is not the same as everyone who is listening — start
the one you want first:

```sh
cd agents && AGENT_NAME=angel uv run python -m core.main
# or blair, charlie, dana, ethan, philip, mock — a comma-separated list, or '*' for all
```

Nobody home is now said rather than hung: the page warns after 60 seconds and the
analyst is released after 90, instead of the request sitting on a 15-minute
deadline with the name locked.

### Questions worth asking

Real business questions with an answer somebody has already checked against the
running stack, which is what makes them useful for judging what comes back. A
question whose answer nobody knows tells you only that the page works.

**Nothing is staged.** These stand true whenever the stack is up:

| ask | it needs | a good answer |
|---|---|---|
| *I'm writing the shipping section of our help page. As things stand right now, which countries can we actually deliver to, and with which carrier for each? Prices and delivery times too if you can get them.* | the shop, three tables joined | two markets — US in zone 9 with two carriers, Canada in zone 10 with one — and it says the price carries **no currency**, so naming one would be a guess |
| *Marketing is deciding what to promote next quarter. For the products we sell, can you give me what we have in stock and how much traffic each one actually gets? I want to know where it is worth spending.* | the shop **and** the analytics | 51 active products, 49 of them out of stock. The join is the whole task: the analytics cannot count a page nobody visited, and the shop knows nothing about attention |
| *We sell into two markets and I have no idea whether they behave the same. For today so far: where are our visitors coming from, and do they buy at the same rate depending on the country? Same question by device while you are at it — are phones converting like desktops?* | the analytics **and** the shop | visitors by country and by device set against orders. Two populations that do not share a key, which a careful answer says out loud |

**These need an incident staged first** — asked against a healthy stack they are
answerable and dull. Staging one is a deliberate change to the running company
(editing the ERP drop, stopping a service), never something a page does:

| ask | staged |
|---|---|
| *We've had complaints from customers in the last 5 minutes. It seems we have a problem — please investigate.* | `carrier_withdrawn` — Canada loses its carrier, and nothing anywhere errors |
| *I can't get any visitor figures this morning. Are we still getting traffic and orders, or is something wrong with the business?* | `tracker_blind` — the analytics is down while the shop keeps selling |
| *Can you work out our conversion funnel for the last hour? I want it from visits through to paid orders, with the drop-off at each step, so I can see where we lose people.* | `conversion_funnel` — the two sides count different populations and cannot be nested |

### Checking the page itself

`mock` is an employee with the loop taken out: a fixed script of steps and one
fixed answer, no model, **no cost**. Use it to exercise the page — the trace, the
folds, the receipt — without spending anything. `MOCK_DELAY_S=2` slows it to a
readable pace.

```sh
cd agents && AGENT_NAME=mock MOCK_DELAY_S=2 uv run python -m core.main
```

It ignores the model you pick but reports it, so it is also how to see what a
question *would* cost on each tier: the same run prices at ~$0.002 on luna,
~$0.021 on terra and ~$0.051 on sol.

### What a run costs

The employee prices its own run at its final return, from the rate card in
`agents/core/prices.py` — the one place this repository states a
price. The page shows tokens always, and money only when there is a number to
show: `Billed` when the loop reported a real charge, `Estimated` when it is
tokens at the published rate, and **nothing at all** for a model nobody has
transcribed. Unpriced is not free.

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
**https://portal.archipellabs.test**
([`config/gateway/nginx.conf`](../workspaces/default/config/gateway/nginx.conf)); in
production that's a subdomain. It reads the DB DSN from the shared `SIMULATORDB_URL`.
