# camel — the integration layer

Apache Camel carries data between TimberWorks' systems. Routes are **code**:
YAML DSL in `routes/`, reviewed in pull requests, mounted read-only into the
container. Nothing is designed in a UI.

Run by `docker-compose-integration.yaml` via Camel JBang — `camel run
--source-dir=/routes --dev`. So **adding a route is adding a file**, and editing
one reloads it live without a restart.

## The workflows

| Route | File | Direction | Trigger |
|---|---|---|---|
| `health` | `health.camel.yaml` | — | timer, every 30s |
| `carriers-from-file` → `carriers-reconcile` → `carriers-prune` | `carriers.camel.yaml` | ERP → shop | `carriers.csv` changes |
| `suppliers-from-file` → `suppliers-reconcile` | `suppliers.camel.yaml` | ERP → shop | `suppliers.csv` changes |

Master data comes from `sidecars/erpfile`, a directory pretending to be an ERP,
reachable over SFTP. Outbound documents will be written back into its `out/`.

A feed is several routes, not one: a source adapter, a reconciler, and for
carriers a prune pass — see *Built for the ERP that replaces the files* below.

### `health` — is the runtime alive?

A timer logging a line every 30 seconds. Deliberately trivial and dependency-free:
it is the smoke test for the container, the mount and the YAML loader, so when a
real route misbehaves this is what says whether the runtime itself is healthy. If
this is quiet, nothing else is worth debugging.

### `suppliers-*` — who we buy from

Reads `suppliers.csv` and makes the shop's supplier list match it.

Per row: look the supplier up by name, then `POST` a new one or `PATCH` the
existing one with its name and `active` flag. Nothing else — no products are
linked, and nothing in the storefront consumes suppliers yet.

It exists for two reasons. It proved the file → shop **write** path on a flat
entity (a name and a flag) before carriers had to solve zones and prices on top.
And suppliers are the first station of the public roadmap, so it is not
scaffolding to be thrown away.

Reconciling, not consuming: running it twice in a row changes nothing the second
time.

### `carriers-*` — who we ship with, where, at what price

Reads `carriers.csv`, one row per *(carrier, country)*, and steers the carriers
the shop already has.

The file is a **snapshot**, not a set of changes, so the route makes the shop
match it — see *Full snapshot, loaded as a merge* below for how, and why it is
not the obvious way.

A carrier named in the feed that does not exist in the shop is **logged and
skipped, not created** — provisioning creates carriers, the feed only steers
them.

That boundary is forced as much as chosen. The Webservice exposes `carriers`,
`deliveries`, `price_ranges` and `zones`, but there is no `carrier_zone`
resource, so zone *coverage* cannot be set through the API at all. Provisioning
owns countries, zones and coverage; the feed owns existence, `active`, delay and
price. It costs nothing, because a carrier with no delivery row for a zone quotes
nothing — the effective switch is on the feed's side of the line.

This is the route the reference incident runs through, and it gives two distinct
levers:

| Edit to `carriers.csv` | Effect |
|---|---|
| `active` → `0` | that carrier disappears from **every** market at once |
| delete the `CA` row | that carrier stops quoting for **Canada**, the US untouched |

The second is the one that matters: it degrades one market while the other keeps
selling, which is what makes the two independently observable.

## Built for the ERP that replaces the files

Each feed splits at a `direct:` endpoint:

```
carriers-from-file  ──▶ direct:carriers-snapshot ──▶ carriers-reconcile ──▶ carriers-prune
   SFTP + CSV                (the contract)              PrestaShop
```

They change for different reasons. The **source adapter** changes when the ERP
changes; the **reconciler** changes when PrestaShop changes. Splitting them is
what makes the eventual swap a one-file job: add `carriers-from-erpnext` handing
the same list of rows to `direct:carriers-snapshot`, delete the file route, and
the reconciler never knows. Both can run side by side during the migration.

The contract between them is deliberately nothing more than *"a list of rows with
these keys"* — no schema file, no registry. In EIP terms: **Channel Adapter** →
**Canonical Data Model** → **Message Translator**.

It is a *snapshot* rather than a change feed on purpose. Every ERP can produce a
full extract; change events are vendor-specific and usually the least reliable
part of an ERP's API. Building on deltas would couple this layer to whichever ERP
arrives, which is the coupling the split exists to avoid.

## Where the endpoints are configured

`routes/application.properties` — picked up automatically from `--source-dir` —
holds the three endpoints, so a shop call is one line at the use site:

```yaml
- to: "{{shop.api}}/carriers?httpMethod=GET&{{shop.auth}}"
```

Everything goes in the URI, with no `parameters:` block beside it. That is not a
style preference: the YAML DSL rejects a `uri:` containing a query string
whenever a `parameters:` block sits next to it (*"Uri should not contains query
parameters"*), so the two forms cannot be mixed — and only the all-in-the-URI
form lets the shared options live in one place instead of being retyped, six
lines at a time, at every call.

## Full snapshot, loaded as a merge

The feed is a full extract every time. There are two textbook ways to load one:

| | What it does | Costs |
|---|---|---|
| **truncate-and-load** | wipe the target, rebuild it from the file | the target is empty in between |
| **merge** | upsert what the file lists, then delete what it no longer lists | needs a key to match rows on |

`carriers-reconcile` **merges**, and the first version did not — which is the
more interesting half of the story.

Truncate-and-load is genuinely simpler: delete every delivery row for a carrier,
recreate one per country in the file, and removal falls out for free because a
dropped line is never recreated. It also left the shop **quoting no shipping at
all for about a second on every run** — measured at 552ms, and 3.3s on a slower
pass. Not only when something was withdrawn: on a price change, on a `touch`, on
a container restart. And not scoped to the carrier being edited, because the wipe
looped over every row in the file. Editing Canada briefly took the US down too.

That is not a bug in the implementation, it is the pattern's defining property —
and it is precisely why real master-data batches run at 3am. **We want the
opposite**: the feed is watched and lands within seconds, so a change shows up
while someone is still looking at the screen. A load that runs while customers
are checking out has to be a merge.

Merging needs a key to match existing rows on, and this is the one entity where
we have one. Suppliers and carriers have no field for our technical id (see
*Identity, and a known defect*), but a delivery row is identified by
*(id_carrier, id_zone)* — both things the feed already knows and the Webservice
can filter on. So the row is found and `PATCH`ed in place.

`carriers-prune` is the other half. Upserting alone can never notice a row that is
**gone**, because there is nothing left to iterate over; so the shop's delivery
rows are compared against the whole snapshot and the unlisted ones removed. It is
the only place anything is deleted, it is scoped to carriers the feed actually
manages, and it touches nothing the file still names.

The observable difference: a delivery row now keeps its **id** across runs.
Rebuild it and the ids change every time — which is what the scenario test
asserts, because "Canada is gone and the US still works" was equally true of the
version that took the US offline for a second on the way.

## The shape every feed route follows

```
sftp consumer  →  unmarshal CSV  →  split rows  →  look up  →  create or update
   (read in place, never moved)                                      │
                                                                     └── log
```

These routes **reconcile**; they do not consume. The source is master data, so it
is state rather than a message — read in place and left exactly where it is.
Running one twice in a row is a no-op by construction.

Four consumer options carry more weight than they look:

- **`noop=true`** — read in place, move nothing. This is the flag that says "this
  file is state". An earlier design used `move=archive/`, which is a *transfer*
  idiom: it ate the source of truth and then needed a seeder container to keep
  putting it back.
- **`idempotent=true` + `idempotentKey=${file:name}-${file:modified}`** — without
  it, reading in place means re-reading forever. Keyed on last-modified, a route
  fires once per real change to the master data and stays quiet in between.
- **`readLock=changed`** — a poller will happily read a file that is still being
  written and parse a truncated list. For `carriers.csv` that means silently
  dropping whichever countries had not landed yet, which is the reference
  incident produced by accident. `changed` waits for size and mtime to settle.
- **`moveFailed`** — deliberately *absent* now. With `noop=true` there is nothing
  to move; a parse failure is a failed exchange, and error handling belongs in
  the route rather than in the filesystem.

`delay=3000` is a demo affordance and worth naming as one: a real supplier feed
is a nightly batch. Three seconds exists so an edit made on stage shows up while
someone is still looking at it.

## Which PrestaShop API these routes use, and why

PrestaShop ships two. Both specs are in `simulator/openapi/`.

| | Legacy **Webservice** (`/api`) | **Admin API** (`/admin-api`) |
|---|---|---|
| Format | XML | JSON |
| Auth | Basic (key as username) | OAuth2 |
| Partial update | `PATCH` (works — see below) | `PATCH`, by design |
| Resources | everything, incl. `carriers`, `deliveries`, `price_ranges`, `countries`, `zones` | **18 only** |
| Carriers / deliveries | ✅ | ❌ **absent** |

**These routes use the legacy Webservice**, and not because it is nicer. It
isn't: the Admin API is JSON instead of hand-built XML, has an OpenAPI contract,
offers conveniences like `toggle-status` and bulk enable/disable, and uses OAuth2
rather than all-or-nothing Basic auth. Credentials for it already exist —
`CreateAdminApiClient` provisions them.

The decision is forced by one fact: **the Admin API has no carriers and no
deliveries.** Its resources are addresses, api-clients, attributes, categories,
contacts, customers, features, hooks, languages, modules, products, stores,
suppliers, tabs, tax-rules-groups, titles, webservice-keys and zones. Carriers
carry the incident, so they stay on legacy regardless — and running two APIs, two
auth schemes and two payload formats through one integration layer costs more
than it buys today.

Worth revisiting when either lands:

- **products or categories become feed-driven** — that is where building XML by
  hand in YAML gets genuinely painful and JSON + `PATCH` pays for itself;
- **agents need scoped access to the shop** — OAuth2 scopes are a real credential
  boundary, which is what `doc/agent-org-lab.md` §7 argues access must be. Basic
  auth cannot express one.

## PrestaShop's Webservice: four traps, all silent

Three of these return an empty list rather than an error, and the fourth reports
success while breaking something elsewhere — which is why they are commented at
each use site rather than trusted to memory.

1. **Host header.** PrestaShop redirects any request whose Host does not match
   its canonical domain, so calling the container by service name returns 302 and
   no data. Use the endpoint option `customHostHeader` — `setHeader: Host` does
   *not* work, because the HTTP producer filters that header and derives it from
   the URI.
2. **Brackets must stay literal.** `display=[id]` percent-encoded to
   `display=%5Bid%5D` is *ignored*, not rejected. Queries are therefore built by
   hand into `CamelHttpQuery`, which the producer sends verbatim. (Same trap from
   the shell: `curl` needs `-g`, or it reads `[…]` as a glob range.)
3. **The response shape changes with the result count.** A match returns
   `{"suppliers":[…]}`, an empty result returns a bare `[]`. Reading `.suppliers`
   blindly fails only when nothing matched — the common case, and the least
   likely to be noticed.
4. **`PUT` is a full replace — use `PATCH`.** Every field omitted from a `PUT`
   body is *blanked*, and the call still returns 200. See below.

### `PUT` blanks what you omit, and the damage surfaces elsewhere

The carriers route originally sent `active` and `delay` with `PUT`. That silently
zeroed `id_reference`, a field it never mentioned.

`id_reference` is how PrestaShop tracks a carrier across edits — and, critically,
how `ps_module_carrier` maps **payment modules** to carriers. With it zeroed, the
shop had carriers and shipping prices that all looked correct, and no payment
method at all. Checkout then failed at the *payment* step: one stage past the
change, in a different subsystem, with nothing in any log connecting the two.

`PATCH` on the legacy API updates only what is sent. Verified rather than
assumed: patching `active` alone left `id_reference`, `name`, `shipping_method`
and `need_range` untouched.

**Both routes use `PATCH` for updates.** If a future route needs `PUT`, it must
read the current record and write it back whole — the field it forgets will not
be the one it was thinking about.

## Identity, and a known defect

Feed rows carry a technical id (`supplier_id`, `carrier_id`). PrestaShop has
nowhere to store it — `ps_supplier` is (id, name, active) and has no reference or
custom field. The webservice advertises `link_rewrite`, but no such column
exists, so filtering on it matches nothing *silently*: an existence check built
on it always answers "no", and every run creates a fresh row. Two runs of a
three-row feed produced six suppliers before this was caught.

Carriers have an `id_reference`, which looks like the field for this — but
PrestaShop owns it. Editing a carrier in the back office creates a new row
reusing the same reference; that is its versioning mechanism, not a spare column.

Matching therefore falls back to `name`, for both. The cost is explicit and
unfixed, and has been observed rather than predicted: **renaming a row in the
feed creates a second record in the shop**, leaving the original orphaned.

The fix is not a cleverer field to match on — it is a cross-reference of our own
(`source_id → shop_id`), which needs the store described in
`doc/agent-org-lab.md` §4. Until then this is an interim with a known defect,
not a finished design.

## Working on routes

```bash
docker compose up -d camel                 # start
docker logs -f camel                       # watch
```

Edit any file in `routes/` and Camel reloads it within seconds — no restart, no
build. **Deleting** a route file is the exception: the watcher throws
`FileNotFoundException` for the removed resource and the context stops reloading
until the container is restarted. Remove a route, then `docker compose restart
camel`. There is no Maven project and no compile step: `camel run` loads the YAML
directly, which is what keeps a JVM component cheap to live with in a stack that
is otherwise Python and PHP.
