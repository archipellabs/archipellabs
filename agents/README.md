# Agents — the simulated staff

One directory per simulated employee, under `roles/`. What distinguishes them is
what they are *handed* — a toolset or a desk — because the point of this arc is
that employees have **separate access**, and access is the thing being measured.

| | who | loop | what it is handed |
|---|---|---|---|
| [`roles/angel/`](roles/angel/) | read-only analyst, reaching the shop, Matomo, Loki and the ERP feed | pydantic-ai | rich tools |
| [`roles/blair/`](roles/blair/) | evidence-first analyst — compact bounded reads plus local table algebra | pydantic-ai | compact tools |
| [`roles/charlie/`](roles/charlie/) | the same job, with the loop handed to **opencode** over MCP | opencode | thin tools |
| [`roles/dana/`](roles/dana/) | **the control** — opencode's loop with Angel's tools, copied verbatim | opencode | Angel's tools |
| [`roles/ethan/`](roles/ethan/) | no tools at all: documentation, a shell, and requests it writes itself | codex / opencode | a desk |
| [`roles/philip/`](roles/philip/) | Ethan's desk plus a skill for analysing its own workspace | codex / opencode | a wider desk |
| [`roles/mock/`](roles/mock/) | **not an analyst** — a fixed script of steps and one fixed answer, for testing everything around a loop without a model | — | nothing |
| [`core/`](core/) | what they all share: the brief, the contract, the loops, records, queue names | — | — |

Six employees doing one job, so that a campaign can hold everything but one thing
still. Angel against Dana isolates the **loop**, since only that differs. Charlie
against Dana isolates the **toolset**. Ethan against Angel isolates something
larger: whether an analyst needs tools at all, or only documentation and a shell.

**One interface, and it was not always.** Every employee is an `Identity` — a
name and a way to build a loop — behind one `Harness` protocol, answering
`<name>.investigate` with the same `Ticket` and narrating on the same
`analyst.*` topics in the same closed step vocabulary. Before that, two lineages
had grown apart on three axes at once: different request field names, different
topics, different step words. A page that tried to call all of them found there
was no one door, and the verdict it displayed for half the staff was empty.

**The brief is one text for all of them**, in `core.brief` — several wordings
would mean a campaign comparing wordings. The single exception is mechanical: the
loops that cannot be handed a type return prose, so they are told the shape to
reply in. It says how to answer, never what to look for.

Grading lives outside every agent, deliberately: one that could see its own
rubric would be measuring the rubric.

## Naming

People's first names, in alphabetical order of introduction. Three rules, each
learned from something concrete:

**Epicene.** The name must not imply a gender. These are processes, and a report
that says "he decided" about one has smuggled in a fact nobody established. It
also removes a decision with no bearing on the experiment.

**ASCII, no accents.** A name becomes a directory, an environment variable
(`AGENT_*`), a log field and a run id. `Chloé` is a worse identifier than
`Charlie` for reasons that have nothing to do with taste.

**No prefix collision with an infrastructure service.** The stack already logs as
`camel`, `alloy`, `loki`, `grafana`, `matomo`, `portal`, `prestashop`,
`simulator`. `Camille` was rejected on this alone: investigations spend much of
their time grepping the `camel` log, and an ambiguous `cam*` in a trace would
cost most at the exact moment someone is reading it.

## One project, one image, however many processes you want

Each employee used to be a self-contained project — its own `pyproject.toml`,
its own lock, its own virtualenv — on the stated grounds that two agents sharing
an environment cannot hold different permissions.

**That argument was measured and did not hold.** The union of the seven
dependency sets resolves to exactly the packages the seven already carried: 66 of
them, none added, because 46 were common to all seven and the rest were a subset
somebody happened not to install. Seven locks and seven virtualenvs were buying a
guarantee that was already free.

The boundary they were protecting is real, and it lives somewhere else:

- **What a loop is handed** is its `Identity` — a toolbox, or a desk with an
  allow-list of credentials. Two employees in one process still cannot reach each
  other's tools, because neither is given the other's.
- **What a shell can read** is `core.harness.desk.child_env`, which *builds* the
  subprocess environment from the resolved configuration rather than inheriting
  this process's. Under codex that was once contained by the vendor's own
  sandbox setting; opencode has no such setting, so until it was built here a
  `bash: allow` loop could read the queue URL and write onto its own action
  stream — the investigated system driving the investigator.

So there is one project, one lock, one `.env`, and one image. `AGENT_NAME` decides
who a container is: a name, a comma-separated list, or `*` for all of them. One
container per employee isolates a crash; one container for all seven costs a
quarter of the memory. **Nothing about an employee changes between them** — each
keeps its own `max_slots=1` and its own named configuration, and the bus still
routes on `<agent>.investigate`, so a caller cannot tell which arrangement it
reached.

```sh
uv sync
AGENT_NAME=mock uv run python -m core.main       # free: no model, fixed answer
AGENT_NAME=angel,philip uv run python -m core.main
```

The image is built from `Dockerfile` here; `workspaces/default/docker-compose-agents.yaml`
runs angel and philip as two services off it.

**The action carries the employee's name and the events do not**, and that
asymmetry is load-bearing. An action has exactly one correct executant, so two
containers serving one action name would split the tickets between themselves
silently, each looking like it was working normally. Events fan out instead — one
consumer group per subscriber — so a page tailing `analyst.step` sees the whole
staff and keeps seeing it at the next hire.

The campaign and the queue share `roles/<name>/investigate.py`, so a run started
by the lab and a run started by a `call` produce comparable records.
