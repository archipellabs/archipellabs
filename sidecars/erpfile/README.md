# erpfile — the company's master data

A simplified ERP whose entire storage engine is a directory. `data/` holds what
TimberWorks knows about itself: who it ships with, who it buys from, and later
what it sells.

    data/carriers.csv     who we ship with, where, and at what price
    data/suppliers.csv    who we buy from

## This is MDM, not file transfer

The files are **state**, not messages. They are not delivered, consumed and
archived — they simply are what the company currently believes. Everything
follows from that:

- They live in **git**, are edited in a pull request, and are mounted
  **read-only** into the container. The integration reads them; it cannot rewrite
  the company's master data as a side effect of reading it.
- Camel reads them **in place** (`noop=true`) and re-reads only when a file
  actually changes. Nothing is moved, so nothing needs putting back.
- The audit trail is **git history** — author, timestamp, diff — rather than a
  folder of timestamped copies.

An earlier design had `in/`, `archive/` and a seeder container copying files into
a drop. All three existed only because the consumer ate its own source of truth.
Treating the files as state removed all three.

`out/` on the running container is the one writable area, for **derived**
documents — the orders journal to come. Derived is not master data and does not
belong in git.

## Identity

Every row carries a technical id (`carrier_id`, `supplier_id`) alongside a
human-readable code. The id is the identity; the code and the name are labels.

**Known defect.** PrestaShop has nowhere to store that id — neither suppliers nor
carriers have a usable custom field — so the integration matches on `name`.
Renaming a row in the feed therefore creates a *second* record in the shop rather
than updating the first. Observed, not theorised. The fix is a cross-reference of
our own (`source_id → shop_id`).

Note `XBORDER` shares one `carrier_id` across two rows: the natural key is
*(carrier_id, country)*, one row per country served.

## Who owns what

| | Owner | Why |
|---|---|---|
| Countries, zones, currencies, carrier↔zone coverage | provisioning (`sidecars/prestashop`) | which markets the shop sells to is a shop decision |
| Carrier existence, `active`, price per country | this data | who we ship with is master data |
| Suppliers | this data | — |

The split is not only philosophical: PrestaShop's Webservice has no
`carrier_zone` resource, so coverage cannot be set through the API at all. What
it does expose is `deliveries` — and a carrier with no delivery row for a zone
quotes nothing — so the *effective* switch lives here even though the coverage
row does not.

`suppliers.csv` is deliberately rougher than `carriers.csv`: nothing in the shop
consumes suppliers yet, so it exists to prove the write path and to hold the
first station of the roadmap. Carriers carry the incident, and got the care.

## Changing them

Edit a file and commit. Camel notices within seconds and reconciles the shop —
no seeding step, no restart.

Two levers, two different incidents:

    active → 0            the carrier disappears from every market at once
    delete the CA row     that carrier stops quoting for Canada, US untouched

So a change to the company's master data is **a diff in version control**,
including a deliberately broken one: the reference incident in
the lab's reference incident arrives with an author, a timestamp and a diff, exactly
as a real master-data change would.
