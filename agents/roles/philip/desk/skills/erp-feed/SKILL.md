---
name: erp-feed
description: Read the company's ERP master data: flat CSV files dropped on an SFTP server, currently carriers and suppliers. Use for any question touching reference data (carriers, shipping options, suppliers, sourcing) or where the shop's configuration may have come from upstream. Ships its own SFTP tool because nothing on this machine speaks SFTP, and explains why this system has no contract and raises no errors.
---

The ERP exchanges master data as **files**, dropped on an SFTP server. There is
no HTTP API here, and therefore no OpenAPI document. That absence is worth
knowing on its own: this is the part of the information system with no contract
at all. Nothing declares these columns. The header row of each file is the whole
schema.

`FEED_HOST`, `FEED_PORT`, `FEED_USER` and `FEED_PASSWORD` are in the
environment.

## How to start

1. **Use the tool this skill ships.** Nothing on this machine speaks SFTP:
   `sshpass` is not installed, and the system `curl` is built **without** SFTP
   support. Any instinct to reach for either is from a manual, not from this
   environment, and following it ends with a wrong conclusion that the
   credentials are unavailable.
2. **Run it with `"$PYTHON"`, never `python3`.** `$PYTHON` points at the
   interpreter that has `paramiko`. The system one does not, and under it the
   script fails with `ModuleNotFoundError`, which reads like an unreachable
   feed rather than the wrong interpreter. Keep the quotes.
3. **List the root first.** Paths are relative to the drop root, and the root
   holds a single `data/` directory.
4. **List `data/`.** That is where the files are. Note the modification times
   while you are there: `ls` prints them, and they tell you when each feed last
   changed.
5. **Read a file.** `head` for the header and a few rows, `cat` for the whole
   thing. These files are small today, so `cat` is usually fine.

## The tool

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py <command>
```

It reads `FEED_HOST`, `FEED_PORT`, `FEED_USER` and `FEED_PASSWORD` from the
environment. It only reads: there is no write command, and no way to change the
drop from here.

| command | what it does |
|---|---|
| `ls [path]` | kind, size in bytes, UTC mtime, name. Defaults to the root. |
| `cat <path>` | the whole file to stdout |
| `head <path> [n]` | the first `n` lines, default 20 |

### Worked commands

List the drop root:

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py ls
```

Output has the shape below. The leading `d` marks a directory, `-` marks a
file:

```
d       128 2026-01-01T00:00:00Z data
```

List the directory that holds the files:

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py ls data
```

```
-       308 2026-01-01T00:00:00Z carriers.csv
-       344 2026-01-01T00:00:00Z suppliers.csv
```

`ls` on a single file gives one row, which is how you check one file's size and
mtime without listing the directory:

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py ls data/carriers.csv
```

Header plus the first two rows:

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py head data/carriers.csv 3
```

Just the header, which is the only schema this system publishes:

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py head data/suppliers.csv 1
```

The whole file, **into your own workspace**, where you can parse it:

```
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py cat data/carriers.csv > data/erp_carriers.csv
```

Two different `data/` directories are in play and it is worth keeping them
apart. The path you pass to `feed.py` is remote, on the drop. The path after `>`
is local, in your workspace, and it is the copy you can open twice, join against
something else, and count without asking the feed again. `ls` and `head` are
cheap enough to read on screen; a whole file is not something to read, it is
something to load.

### Times printed by `ls`

`ls` prints modification times in **UTC**, suffixed `Z`. The shop reports in
`SHOP_TIMEZONE`, so the two are not directly comparable without converting one
of them.

### When something fails

- `not set in the environment: FEED_HOST` and similar: the credential is
  genuinely absent. This is the only error that means the credentials are the
  problem.
- `ModuleNotFoundError: No module named 'paramiko'`: you used `python3`. Re-run
  with `"$PYTHON"`.
- `FileNotFoundError: [Errno 2] No such file`: the path is wrong. `ls` the
  parent rather than guessing again.

## What is in the drop

The root holds one directory, `data/`. Inside it, two files. List before
assuming a filename rather than trusting this paragraph, which is true today.

### `data/carriers.csv`

The carriers the company intends to offer, and where.

| column | shape | meaning |
|---|---|---|
| `carrier_id` | UUID | stable identity of the carrier upstream |
| `carrier_code` | short uppercase token | the carrier's business code |
| `carrier_name` | text | the name a customer would see |
| `active` | `1` or `0` | whether the carrier is to be offered |
| `country` | ISO 3166-1 alpha-2 | the country this row covers |
| `price` | decimal, 2 places | shipping price for that country |
| `delay_days` | integer | quoted delivery delay in days |

The grain is **one row per carrier per country**. A carrier that serves two
countries appears twice, with the same `carrier_id` and `carrier_code` and a
different `country`, `price` and `delay_days`. Neither `carrier_id` nor
`carrier_code` is unique on its own: the key is the pair with `country`.

`active` sits on the row, not on the carrier. Read it per row.

### `data/suppliers.csv`

Who the company sources from.

| column | shape | meaning |
|---|---|---|
| `supplier_id` | UUID | stable identity of the supplier upstream |
| `supplier_code` | short uppercase token | the supplier's business code |
| `supplier_name` | text | the supplier's name |
| `country` | ISO 3166-1 alpha-2 | where the supplier is |
| `contact_email` | email | ordering contact |
| `active` | `1` or `0` | whether the supplier is in use |

## Reading the files

CSV with a header row, comma separated, UTF-8, newline-terminated.

- **Read the header, do not assume column order.** Nothing pins it, because
  nothing declares it. `head <path> 1` costs one command.
- **Parse, do not split on commas.** A quoted field may contain a comma or a
  newline, so `split(",")` and a line count can both be wrong on a file that is
  perfectly valid. `csv.DictReader` handles both.
- **Decode as `utf-8-sig`, not `utf-8`.** A feed that ever passes through a
  spreadsheet can pick up a byte-order mark, an invisible character at the very
  start of the file. Decoded as plain `utf-8` it stays glued to the front of
  the first column name, and every lookup on that name misses while the file
  looks fine on screen. `utf-8-sig` reads ordinary UTF-8 too, so it is safe
  either way. The shipped tool already does this.
- **Booleans are `1` and `0`,** not `true` and `false`.
- **Timestamps inside the files**, where present, follow shop-local time, not
  UTC. Modification times printed by `ls` are the opposite: those are UTC.

## These files are upstream, the shop is downstream

They are the **upstream truth** for reference data. The shop's own copy is
downstream. An integration reads these files, compares them to the shop, and
reconciles the difference.

So when the shop and a feed file disagree about reference data, the feed is what
the company intends and the shop is what it currently has.

The direction runs one way only. Nothing you can do from here changes the feed,
and nothing done in the shop propagates back into these files.

### Comparing a file to its downstream copy

Reading a feed file tells you what the company intends. It does not tell you
whether the shop has it. Only the comparison does, and the comparison is four
commands. Worked here on `suppliers.csv`, which is the smaller of the two files;
the shape is the same for any of them.

```bash
"$PYTHON" .agents/skills/erp-feed/scripts/feed.py cat data/suppliers.csv > data/feed_suppliers.csv
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" \
  -o data/shop_suppliers.json -w 'HTTP %{http_code}  %{size_download} bytes\n' \
  "$SHOP_API_URL/suppliers?output_format=JSON&display=[id,name]"
```

Then join them in a script rather than by eye, and print both directions:

```python
import csv, json
feed = {r["supplier_name"]: r for r in csv.DictReader(open("data/feed_suppliers.csv", encoding="utf-8-sig"))}
shop = {s["name"]: s for s in json.load(open("data/shop_suppliers.json"))["suppliers"]}
print("upstream", len(feed), "downstream", len(shop))
print("in feed, absent from shop :", sorted(feed.keys() - shop.keys()))
print("in shop, absent from feed :", sorted(shop.keys() - feed.keys()))
```

```
upstream 3 downstream 3
in feed, absent from shop : []
in shop, absent from feed : []
```

Two empty lists is what agreement looks like, and it is worth seeing once so that
a non-empty one is recognisable. Three things make this worth the four commands:

**Print both directions.** A row the shop has and the feed does not is a
different fault from a row the feed has and the shop does not, and they need
different fixes. One direction alone answers half the question.

**Count is not agreement.** Equal totals on both sides can hide one row added and
one removed. Compare the sets, never the lengths.

**Compare at the grain the file declares, not at the entity.** Each file states
its grain in the section above; it is not always one row per thing. Where the
grain is finer than the entity — several rows describing one name — then every
name can be present on both sides while what the file actually says about them
has changed. Comparing the entity list finds nothing, because the entity list is
the same in both worlds. Join on the full grain or the comparison cannot fail.

## What the drop does not keep

There is no history here. Each file holds the current state, with no previous
version and no changelog beside it. The modification time from `ls` is the only
trace that a file changed, and it records when, never what.
