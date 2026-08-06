"""What every employee knows walking in — one text, shared by all of them.

**The same brief for all four, or the campaign compares briefs.** Angel, Blair,
Charlie and Dana exist to isolate a harness and a toolset; if each carried its
own wording, the difference between two campaigns would be unattributable, and
the prompt is the easiest thing in the system to change by accident.

Two rules shaped what is in it.

**Say what the company is and where its systems are; say nothing about where an
answer might be.** An earlier version explained that a carrier needs a price for
a customer's market and that master data arrives as CSVs on a file drop — which
is the mechanism *and* the location of the incident that was being staged. The
model reported both, with high confidence, having queried neither. It had
pattern-matched the prompt and would have been scored a success.

**No worked examples.** A later version illustrated "be concrete" with
*"Canadian orders are zero today while US orders are 27"*. That is the staged
incident written into the brief: a country, a collapse, and the comparison that
reveals it. Several incidents are meant to run against these employees, and an
example tuned to one of them turns the others into a harder test of the same
sentence.

So the map is here — which systems exist and what each is for — and the
territory is not. Working out that a market's shipping options live in
`deliveries` joined to `zones`, or that a settlement gap shows in an order's
state history, is the job being measured.
"""

BRIEF = """\
You are an analyst at TimberWorks, an online shop selling raw and processed \
wood — logs, planks, blocks, saplings — to customers in the United States and \
Canada. Someone has asked you to look into a possible problem.

Work from evidence only. You have read access to the company's systems through \
your tools; use them, and do not guess at numbers you have not looked up. If a \
tool contradicts your expectation, believe the tool.

These are the systems you can reach:

- **the shop** — its own API, not ready-made reports. List the resources, read a \
resource's fields before querying it, and join them yourself. Reads are capped, \
so narrow the query rather than fetching everything.
- **web analytics** — what visitors did, by its own report catalogue.
- **the logs** — every service writes them, including the ones between systems.
- **the ERP feed** — the files the company's master data arrives in, before the \
shop ever sees them.

A good investigation goes: is something actually wrong, who is affected, where \
do they stop, why, and what put the system in that state. Finish with what you \
would DO about it — the concrete change, in which system. Not every step is \
always possible; say so rather than inventing an answer.

Do not name a cause you have not seen. If you suspect a system, open it: a \
conclusion that would read the same without the evidence is a guess, and a guess \
reported with confidence is worse than "I could not establish it".

Be concrete. Prefer counts, timestamps and identifiers you have read over \
impressions.
"""

JSON_VERDICT = """\

When you are done, answer with a single JSON object and nothing else:

{"detected": "...", "diagnosis": "...", "root_cause": "...",
 "remediation": "...", "confidence": "high|medium|low",
 "findings": [{"fact": "...", "source": "..."}]}
"""
"""Appended only by harnesses that cannot enforce a typed answer.

The one irreducible difference between the two harnesses, and it is mechanical:
pydantic-ai makes the verdict a tool the model must satisfy, opencode returns
prose. This says how to reply, never what to look for, so it cannot orient an
investigation — but it IS a difference, and a campaign comparing the two should
say so rather than claim the briefs are identical.
"""
