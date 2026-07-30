# Simulator

A load simulator for the PrestaShop storefront, built on
[`archipellabs-runtime`](https://pypi.org/project/archipellabs-runtime/) 0.3 — a
Redis Streams runtime with three verbs: `call` (send and wait for a result),
`dispatch` (send to exactly one executant) and `emit` (fan out to every
subscriber). There is no HTTP server: the simulator is a runtime `App` of
`Service`s, started from the command line.

Two **external flows** (`src/external_flows/`) simulate what happens to the
company from outside, decoupled through the `customer.arrival` stream:

- **`customer_arrivals`** (producer, `scheduler.py`) — on every tick, computes the
  current traffic intensity, Poisson-samples arrivals, manages an in-memory pool
  of fresh customer identities, builds a website-agnostic business intent, and
  `dispatch`es one `customer.arrival` per arrival. `dispatch`, not `emit`:
  driving the same simulated customer twice would place a duplicate order. Each
  carries a `ttl` of a few ticks, so a backlog built up during an outage expires
  instead of replaying an hour of traffic at once. Returning visitors are a
  later-stage mechanic.
- **`customer_journey`** (consumer, `pool.py`) — an action bounded by
  `max_slots`, backed by one shared Chromium process; each arrival runs a
  Playwright state machine through the storefront. The registration declares
  `params=CustomerArrivalEvent`, so a malformed message is rejected by the
  runtime before the handler runs and reported as a typed `ParamsInvalid`,
  instead of being logged and dropped inside the handler.

Three **internal flows** (`src/internal_flows/`) keep the shop's data in shape,
driving PrestaShop through its Webservice/Admin APIs — never the storefront:

- **`catalog`** (`service.py`) — one service holding both halves: a `catalog.sync`
  action that reconciles the local PIM (`data/pim/`) into PrestaShop (purely
  additive — it never deletes), and a `doctor` producer that `call`s it on a timer
  and logs the summary that comes back. The full pass repairs field and
  association drift as well as missing resources.
- **`stock`** (`scheduler.py`) — tops tracked products back up when their stock
  dips below a floor.
- **`payments`** (`scheduler.py`) — settles the waiting bank wires; nothing else
  moves an order out of "Awaiting bank wire payment".

One **technical flow** (`src/technical_flows/`) acts on the simulator itself
rather than on the company:

- **`configuration`** (`actions.py`) — a `config.apply` action that changes a knob
  on a running simulator, and `config.describe` that reports what is changeable.
  A value goes to the settings table; a flow name flips the runtime's switch
  registry.

The distinction is not filing. A technical flow is **out of universe**: it is not
something TimberWorks does, so it must never show up in the company's data, and
nothing modelling the business imports from it. That is also why it is not a
`services/` package — everything under `src/services/` is a library the flows
call, while this is a mounted flow that nothing imports.

### Flow convention

Each flow is a package under `src/<kind>_flows/<name>/` with a single role-named
entry module, and every one of them exports the runtime component as `service`:

| Entry module | Role |
|---|---|
| `scheduler.py` | a producer — work on a timer (`@service.every`) |
| `pool.py` | a consumer whose lifespan owns an expensive shared resource |
| `service.py` | one domain that both consumes and produces |
| `actions.py` | a technical control surface |

The module's header docstring states its role and topic. Names are declared once
per flow kind in `topics.py` (`Topic`, a `StrEnum`): a caller sends a `Topic`, the
executant binds the same `Topic` with `@service.action(...)`, and they share only
that name — never a reference. `src/app.py` then `include`s each flow's `service`
uniformly.

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
local PIM (`data/pim/`) into PrestaShop, and the **catalog doctor** triggers a full
idempotent reconciliation on a timer. Both are enabled by default
(`CATALOG_ENABLED`, `CATALOG_DOCTOR_ENABLED`). Clearing PrestaShop's install demo
data is a separate, setup-time concern handled by the provisioning sidecar — not
the simulator.

Start the simulator (producer + consumer in one process; Ctrl-C to stop):

```sh
uv run python -m src.app
```

It logs the topology at boot, then streams JSONL journey events on stdout.

## Configuration

Every setting is read through one interface, whatever kind it is:

```python
from src.services.configuration.service import configuration

configuration.get("shop_base_url")
```

Values resolve through three layers, first hit wins:

1. **Dynamic** — a row in the activity database, for the keys in `TUNABLES`.
   Changeable while the app runs.
2. **Static** — the environment, via `.env` or a real variable. A restart.
3. **Default** — the value shipped in `src/config.py`.

`get` is synchronous and never does I/O, because configuration is read where no
`await` can reach — `@service.every(...)` binds a schedule at import,
`include(enabled=)` decides wiring before the loop exists. It answers from an
in-process snapshot — warmed at boot by the two flows that have a lifespan
(`customer_arrivals`, `customer_journey`) and reloaded behind a stale read, so a
change made elsewhere lands within a minute.

To change something on a running simulator, send it to the technical flow:

```python
from src.technical_flows.topics import Topic

await ctx.call(Topic.CONFIG_APPLY, key="base_arrivals_per_minute", value=9)
await ctx.call(Topic.CONFIG_APPLY, key="customer-arrivals", value=False)  # pause
await ctx.call(Topic.CONFIG_APPLY, key="base_arrivals_per_minute")        # reset
```

A **value** is stored in the settings table and picked up by the next read. A
**flow name** flips a runtime switch, which pauses consumption while the stream
keeps filling, so resuming drains the backlog rather than losing it. The
`*_ENABLED` variables are deliberately *not* changeable this way: they gate
`App.include()`, which runs once at boot, so a service left out was never
constructed and no switch reaches it.

### Delivery behavior

`archipellabs-runtime` 0.3 acknowledges a message once its handler has been
run — including when the handler reported a failure, which travels back to the
caller as a typed error rather than as a redelivery. A message whose deadline
passed while it queued is dropped without executing. What is still missing is
reclaim: a message left pending by a *crashed process* is not picked up by
another. The journey flow therefore treats browser-state and infrastructure
failures as terminal, recorded observations, and the catalog doctor re-runs a
full reconciliation on a timer, so catalog convergence never depends on reclaim.
Pending-message reclaim and duplicate-order protection must land together before
customer-arrival delivery can be described as at-least-once.

## Development

Regenerate the PrestaShop API clients after an OpenAPI spec change:

```sh
uv run python scripts/generate_prestashop_clients.py
```

Tests come in four tiers by what they need to run:

- `tests/unit/` — isolated units (fakes for collaborators), fast.
- `tests/component/` — several real components wired in-process over a fake Redis
  (boundaries stubbed), still hermetic and fast.
- `tests/e2e/` — hit live services (PrestaShop, the activity Postgres, a real
  browser); carry the `e2e` marker and are deselected by default.
- `tests/scenarios/` — drive the whole stack and *mutate* it: edit the company's
  master data, wait for the integration layer to reconcile, then judge the result
  by whether a customer can still buy. Slow and stateful; each scenario repairs
  what it broke and asserts the repair landed.

The default lane runs unit + component (everything except `e2e`):

```sh
uv run pytest -m "not e2e"     # what CI runs
uv run pytest -m e2e           # the live-service tier (needs the stack up)
uv run pytest                  # everything
```

Set `DEBUG_SHOW_BROWSER=true` to watch a journey run instead of driving Chromium
headless. It needs a display, so never set it in a container.

Package marker files:

Avoid adding `__init__.py` files unless a package needs explicit initialization
logic or compatibility with tooling that does not support namespace packages.
Keep imports module-based and let Python namespace packages handle directories.
