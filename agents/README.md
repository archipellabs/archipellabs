# Agents — the simulated staff

One directory per simulated employee. Each is a self-contained project with its
own `pyproject.toml`, credentials and tests, because the point of this arc is
that employees have **separate access**: two agents that share a virtualenv and a
`.env` cannot have different permissions, and the boundary is the thing being
measured.

| | who | loop | what it is handed |
|---|---|---|---|
| [`angel/`](angel/) | read-only analyst, reaching the shop, Matomo, Loki and the ERP feed | pydantic-ai | rich tools |
| [`blair/`](blair/) | evidence-first analyst — compact bounded reads plus local table algebra | pydantic-ai | compact tools |
| [`charlie/`](charlie/) | the same job, with the loop handed to **opencode** over MCP | opencode | thin tools |
| [`dana/`](dana/) | **the control** — opencode's loop with Angel's tools, copied verbatim | opencode | Angel's tools |
| [`ethan/`](ethan/) | no tools at all: documentation, a shell, and requests it writes itself | codex / opencode | a desk |
| [`philip/`](philip/) | Ethan's desk plus a skill for analysing its own workspace | codex / opencode | a wider desk |
| [`mock/`](mock/) | **not an analyst** — a fixed script of steps and one fixed answer, for testing everything around a loop without a model | — | nothing |
| [`_core/`](_core/) | what they all share: the brief, the contract, the loops, records, queue names | — | — |

Six employees doing one job, so that a campaign can hold everything but one thing
still. Angel against Dana isolates the **loop**, since only that differs. Charlie
against Dana isolates the **toolset**. Ethan against Angel isolates something
larger: whether an analyst needs tools at all, or only documentation and a shell.

**One interface, and it was not always.** Every employee is now an `Identity` — a
name and a way to build a loop — behind one `Harness` protocol, answering
`<name>.investigate` with the same `Ticket` and narrating on the same
`analyst.*` topics in the same closed step vocabulary. Before that, two lineages
had grown apart on three axes at once: different request field names, different
topics, different step words. A page that tried to call all of them found there
was no one door, and the verdict it displayed for half the staff was empty. What
each directory still owns is what actually distinguishes it — its tools or its
desk, and the `.env` beside them.

**The brief is one text for all of them**, in `core.brief` — several
wordings would mean a campaign comparing wordings. The single exception is
mechanical: the loops that cannot be handed a type return prose, so they are told
the shape to reply in. It says how to answer, never what to look for.

Grading lives in `../research/`, deliberately outside every agent: one that could
see its own rubric would be measuring the rubric.

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

## One agent, one process, one container

Each agent runs alone in its own container. That is what makes the access
boundary real rather than declarative: separate credentials, separate `.env`,
separate Webservice key, and no shared process in which one agent could reach
another's clients.

It also settles the package name. Every agent uses `src` — `angel/src/identity.py`
— which would be ambiguous if two were imported together, and never is, because
they never are. `research/lab/worker.py` puts a single agent directory on
`sys.path` for the same reason.

Work reaches a containerised agent over the queue: `src/app.py` serves
`<name>.investigate` as a runtime action, with `max_slots=1` so one investigation
runs at a time. **The action carries the employee's name and the events do not**,
and that asymmetry is load-bearing. An action has exactly one correct executant,
so two containers serving one action name would split the tickets between
themselves silently, each looking like it was working normally. Events fan out
instead — one consumer group per subscriber — so a page tailing `analyst.step`
sees the whole staff and keeps seeing it at the next hire.

The campaign and the queue share `src/investigate.py`, so a run started by the
lab and a run started by a `call` produce comparable records.

**Not built yet:** no `Dockerfile` and no compose service. Angel runs from source
today. Containerising is what turns "separate access" from an intention into
something PrestaShop enforces.
