# Simulator

A load simulator for the PrestaShop storefront, built on
[`archipellabs-runtime`](https://pypi.org/project/archipellabs-runtime/) — a
producer/consumer runtime over Redis Streams. There is no HTTP server: the
simulator is a runtime `App` started from the command line.

Two external flows, decoupled through the `customer.arrival` Redis stream:

- **`customer_arrivals`** (producer / `Scheduler`) — on every tick, computes the
  current traffic intensity, Poisson-samples arrivals, manages an in-memory pool
  of customer identities (new vs returning), builds a website-agnostic business
  intent, and emits a `customer.arrival` event.
- **`customer_journey`** (consumer / `Pool`) — a pool of workers backed by one
  shared Chromium process; each event runs a Playwright state machine through the
  storefront.

Two **internal flows** (`src/internal_flows/`) keep the shop's data in shape,
driving PrestaShop through its Webservice/Admin APIs — never the storefront:

- **`catalog`** — a `sync` consumer (`pool.py`) that reconciles the local PIM
  (`data/pim/`) into PrestaShop on a `catalog.sync` event (purely additive — it
  never deletes), plus a `doctor` producer (`doctor.py`) that periodically checks
  the live catalogue for drift and emits `catalog.sync` to converge it.
- **`stock`** — a producer (`scheduler.py`) that tops tracked products back up
  when their stock dips below a floor.

They follow the same role-named convention below and are toggled by the same
`*_ENABLED` flags (see `src/config.py`).

### Flow convention

Each flow is a package under `src/external_flows/<name>/` with a single
role-named entry module that exports the runtime component under a predictable
symbol:

- a **producer** → `scheduler.py` exporting `scheduler` (a `Scheduler`);
- a **consumer** → `pool.py` exporting `pool` (a `Pool`).

The module's header docstring states its role and topic
(`<name> — producer|consumer (Scheduler|Pool) of Topic.X`). Event types are named
once in `src/external_flows/topics.py` (`Topic`, a `StrEnum`): the producer
`emit`s a `Topic`, the consumer binds the same `Topic` with
`@pool.flow(consumes=...)` — they share only that name. `src/app.py` then includes
each flow's `pool` / `scheduler` uniformly.

## Setup

```sh
uv tool install openapi-python-client
python3 scripts/generate_prestashop_clients.py
uv sync
uv run playwright install chromium
```

## Run

The runtime needs Redis. It ships in the e-commerce stack:

```sh
docker compose -f ../workspaces/default/docker-compose.yaml up -d
```

The storefront is seeded by the simulator itself: the **catalog** flow syncs the
local PIM (`data/pim/`) into PrestaShop, and the **catalog doctor** detects an
empty or drifted catalogue and triggers that sync on a timer. Both are enabled by
default (`CATALOG_ENABLED`, `CATALOG_DOCTOR_ENABLED`). Clearing PrestaShop's
install demo data is a separate, setup-time concern handled by the provisioning
sidecar — not the simulator.

Start the simulator (producer + consumer in one process; Ctrl-C to stop):

```sh
uv run python -m src.app
```

It logs the topology at boot, then streams JSONL journey events on stdout. Config
comes from `.env` (see `src/config.py`): `REDIS_URL`, `SHOP_BASE_URL`, the
PrestaShop API credentials, and `JOURNEY_SLOTS` (consumer concurrency).

## Development

Regenerate the PrestaShop API clients after an OpenAPI spec change:

```sh
uv run python scripts/generate_prestashop_clients.py
```

Run the tests (unit only by default; integration needs a live PrestaShop):

```sh
uv run pytest -m "not integration"
```

Package marker files:

Avoid adding `__init__.py` files unless a package needs explicit initialization
logic or compatibility with tooling that does not support namespace packages.
Keep imports module-based and let Python namespace packages handle directories.
