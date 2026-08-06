---
name: workspace-analysis
description: Reference for turning saved responses into an answer with the working directory, the shell and Python. Covers the layout of the workspace, checking the shape of a saved response before parsing it, counting with jq, writing and running your own scripts with $PYTHON, joining two saved responses on a shared id, verifying that a join actually matched, and printing an aggregate rather than rows. Consult it when a response is already on disk and needs to be related to another one; it documents no system and reaches nothing.
---

The other four skills tell you how to reach a system. This one is about what
happens after the response arrives, and it applies to all four.

You have a working directory, a real shell and a real Python. Use all three. The
alternative — calling a system, reading the rows that come back, and carrying
them forward in your head — fails in a specific and quiet way: a page of output
read by eye is how a set of two hundred becomes the twenty-five you were shown,
and nothing about the number twenty-five looks wrong afterwards.

## The layout

```
AGENTS.md            your brief
.agents/skills/      these skills
company-ca.crt       the company's certificate authority
data/                every response you fetch, one file per call
*.py                 the scripts you write
```

`data/` already exists. One file per call, named for what it holds, is the whole
convention — the examples in the other skills already follow it, so copying them
gives you the layout for free.

Nothing here is cleaned up between steps, which is the point: a file you fetched
in your third command is still there in your fifteenth, and re-reading it costs
nothing while re-fetching it costs a call and may return something different.

## The two responses everything below works on

So that this file can be run start to finish rather than read, fetch these
first. They are two ordinary collections from the shop, and the `shop-webservice`
skill explains both — nothing here depends on what is in them.

```bash
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&limit=20&display=[id,reference,date_add,total_paid,current_state,valid,id_carrier,id_customer]"
```

```bash
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_order_states.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/order_states?output_format=JSON&language=1&display=[id,name,paid,shipped,logable,delivery,invoice,hidden]"
```

## 1. Look at the shape before you parse it

A saved response is not yet evidence. Two commands tell you whether it is worth
opening, and neither of them prints the body.

```bash
wc -c data/*.json
```

```bash
head -c 300 data/shop_orders.json; echo
```

A 2-byte file is `[]`. A 60-byte file is usually an error envelope. Both arrive
with a perfectly healthy status line, and both read as "no rows" to anything
that does not look.

`jq` answers structural questions directly, and its answers are short:

```bash
jq 'if type=="array" then "bare array, length \(length)" else keys end' data/shop_orders.json
```

```bash
jq '.orders | length' data/shop_orders.json
```

```bash
jq '.orders[0]' data/shop_orders.json
```

Those four — size, first bytes, top-level keys, count — are worth running on
every file you save. They cost nothing and they are how you find out that a call
answered `200` with an error inside it, or that the collection you asked for is
under a key you did not expect.

## 2. Count with a command, never by eye

Anything of the form *how many*, *which distinct values*, *does this set contain
that one* is a command, not a reading exercise.

```bash
jq -r '.orders[].current_state' data/shop_orders.json | sort | uniq -c | sort -rn
```

```bash
jq -r '.orders[].id' data/shop_orders.json | wc -l
```

Two habits go with this. **A count you did not print is a count you guessed**,
so print it. And **a page that ends without warning may have been truncated**:
if a result comes back at exactly the limit you asked for, that is not the size
of the set, it is the size of the page, and the next page exists.

## 3. Write a script, run it, read what it printed

`$PYTHON` is a real interpreter. Keep the quotes: `"$PYTHON"`, never `python3`,
which is a different interpreter with none of the packages the skills rely on.

Write scripts to files rather than passing them with `-c`. A file can be fixed
and re-run when it fails, and it stays on disk as the derivation of the number
you are about to report.

Nothing about the pattern below is particular to the two files it happens to
use: it is two files in, one small table out, and every question that relates
records has that shape whatever the systems involved.

```bash
cat > count_by_state.py <<'PY'
import collections
import json
import pathlib


def load(path):
    """One saved response, as a dict.

    An empty result often arrives as a bare `[]` rather than as an empty
    collection under the key you asked for, so a plain `body["orders"]` raises
    on exactly the case you most need to notice. Returning `{}` here means the
    caller's `.get(..., [])` reports zero, and the count printed below is what
    tells you which of the two happened.
    """
    body = json.loads(pathlib.Path(path).read_text())
    return body if isinstance(body, dict) else {}


orders = load("data/shop_orders.json").get("orders", [])
states = load("data/shop_order_states.json").get("order_states", [])

# Index the smaller side once. A lookup built once and used n times is also the
# only version of this that stays honest as n grows.
#
# `str()` on both sides on purpose: the same identifier arrives as `5` from one
# call and as `"5"` from another, and an unnormalised join between the two
# matches nothing at all while raising no error and printing no warning.
name_of = {str(s["id"]): s["name"] for s in states}
counts = collections.Counter(
    name_of.get(str(o["current_state"]), "UNMATCHED") for o in orders
)

print(f"{len(orders)} orders  x  {len(name_of)} states")
for state, n in counts.most_common():
    print(f"{n:>6}  {state}")
PY
"$PYTHON" count_by_state.py
```

If it fails on a missing file, fetch that response first — the script is the
second half of a pair, and the first half is a call.

## 4. Check that the join matched

This is the step that separates a computed answer from a confident wrong one.

A join between two sets that share no usable key does not fail. It returns
nothing, or it returns everything under a default, and both look exactly like a
finding. `UNMATCHED` in the example above exists for that reason: if it holds
every row, the join did not work and the table below it is fiction.

Three checks, worth running on any join before you believe it:

- **How many rows matched, as a number**, next to how many went in. Print both.
- **One matched row, in full.** Look at it. If the pairing is wrong, it is
  usually obvious at a glance and never obvious in an aggregate.
- **The leftovers.** Rows on either side with no counterpart are often the
  answer rather than an inconvenience: a set present on one side and absent on
  the other is a real fact about the company, not a defect in your script.

If a join matches nothing, suspect the key before the data. The same identifier
appearing as a number and as a string is the first cause. Different grain is the
second: one file may hold one row per thing and the other several rows per
thing, and a lookup built from the second silently keeps only the last of each.

## 5. Print an aggregate, not the rows

A script that prints thirty lines has told you something. A script that prints
three hundred has handed the problem back to you unchanged, and you are once
again reading rows by eye — with an extra step in between that makes it feel
rigorous.

Print counts, sums, distinct values, the two sides of a comparison, the rows
that did not match. If you genuinely need the rows, write them to a file and
query that file instead.

```bash
"$PYTHON" count_by_state.py > out_states.txt && tail -20 out_states.txt
```

### Print the conclusion first

Note what that line does: it keeps twenty lines and discards the rest. That is
safe here only because the script was written to print an aggregate. Apply the
same `tail` or `head` to a script that dumps rows first and summarises after,
and the summary is what gets thrown away.

So order the output deliberately: **the comparison first, the supporting rows
after.** Whatever is truncated should be the part you can re-derive.

Three ways a result gets cut before you read it, all silent:

- **A command's output is capped.** Long output is clipped at a fixed size. The
  cut is at the *end*, which is where a script that dumps-then-summarises put
  its answer. If a result ends mid-record or mid-number, it was cut — treat the
  tail as missing, not as absent.
- **You cut it yourself.** `| head` on a search is a filter, not a preview. A
  search returning ten matches out of forty has answered a different question
  than the one you asked, and the nine you did not see may be the ones that
  contradict the one you did.
- **A query has its own limit.** A capped query returns the newest or oldest N
  and looks exactly like a complete result. Ask for the total separately, and
  compare it against what you received.

Whenever a count decides a conclusion, ask where that count could have been
truncated before believing it.

## 6. A boundary is not an event until you sample it twice

A field that changes value partway down a list looks like something happened at
that moment. Usually nothing did: many states are simply what a record passes
through on its way somewhere else, so the most recent N records sit in the
earlier state permanently, and the boundary moves with the clock.

Before calling a boundary an event, sample the same set again a few minutes
later. If the boundary moved, it is a queue and not an incident. If it stayed
where it was, it is a timestamp worth explaining.

The same applies to a window: a count taken over a period that straddles a
change averages the before and the after into something that resembles neither.
Establish when the change happened first, then measure each side of it
separately.

## 7. What to keep

Leave the files and the scripts where they are. They are the reason an answer
can be checked: a figure with a saved response and a script behind it can be
re-derived by anyone, and a figure recalled from a screen cannot be re-derived
by anybody, including you, ten commands later.

When you report a number, you should be able to name the file it came from and
the script that computed it. If you cannot, the number is a recollection, and
saying so is more useful than reporting it as a measurement.
