"""Ask an employee something and watch it work.

    uv run python -m src.watch
    uv run python -m src.watch --harness opencode "are Canadians able to check out?"

Self-contained: it serves the employee and calls it. Nothing else needs to be
running.

Two things at once, which is the point of it. The question goes out as a `call`
and blocks until an answer comes back. The steps arrive separately, as events
nobody had to ask for, and print as they happen.

That is the shape the bus gives you for free and the reason it has two verbs. A
caller waits for a value; a watcher sees the work. Neither slows the other, and
this script is both at the same time only because it is convenient to be.

It subscribes with a group of its own, so watching does not take events away
from anything else that is listening — and it filters on its own `reference`,
because the topics are shared and every employee's steps arrive on them.
"""

import argparse
import asyncio
import os
import uuid
from typing import Any

from runtime import App, Context, Params, Service

from core import topics
from core.config import load
from core.harness.base import Identity, Kind
from core.service import serve

TTL = "15m"
"""How long the caller waits. An investigation is a model turn, sometimes
several; a shorter deadline reports nothing rather than reporting a failure."""

MARK = {
    Kind.STARTED: ("·", "start"),
    Kind.THINKING: ("*", "thinking"),
    Kind.COMMAND: (">", "run"),
    Kind.OUTPUT: ("<", "got"),
    Kind.MESSAGE: ('"', "says"),
    Kind.TOOL: ("+", "tool"),
    Kind.FINISHED: ("·", "done"),
    Kind.ERROR: ("!", "error"),
    Kind.OTHER: ("?", ""),
}
"""One character per kind, from the standard vocabulary only.

This script never sees a vendor's word, which is the property the whole
translation chain exists to give it: nothing here would change if the loop did.

The words beside the marks are this display's own — `run`, `got`, `says` — and
they are **not** the vocabulary on the wire. Reading them off a terminal and
taking them for the wire's is exactly how a page ended up rendering every step
but one as `other`."""

WIDTH = 96

_ANSWER = ("detected", "diagnosis", "root_cause", "remediation", "confidence")


def show(step: dict[str, Any]) -> None:
    """One line per step, showing the thing that step actually is.

    The first version preferred `command` over `text` whatever the kind, so a
    command and its result printed identically and a skill announced itself
    twice: codex reports a command starting and finishing, and both carry the
    command. Reading the flow was worse than reading the record, which defeats
    the point of a flow.

    So the body is chosen by kind. A command shows what was run, an output shows
    what came back, and the skill is announced once, when it is opened.
    """
    kind = Kind(step.get("kind", Kind.OTHER))
    mark, label = MARK[kind]
    skill = step.get("skill") or ""
    command = (step.get("command") or "").replace("\n", " ").strip()
    text = (step.get("text") or "").replace("\n", " ").strip()
    tool = step.get("tool") or ""

    if kind is Kind.COMMAND:
        # Opening a skill is a command that reads a SKILL.md. Say so, rather
        # than print the `sed` that did it.
        label, body = ("opens", skill) if skill else (label, command)
    elif kind is Kind.OUTPUT:
        if skill:
            # The answer here is the skill's own text, which the reader can
            # already go and read. Its length is the only news.
            label, body = "read", f"{skill} ({len(text)} chars)"
        else:
            body = text
    elif kind is Kind.TOOL:
        body = tool or text
    else:
        body = text or command

    line = f"  {mark} {label:<9} {body}"
    print(line[:WIDTH] + ("…" if len(line) > WIDTH else ""), flush=True)


def main(identity: Identity, harnesses: tuple[str, ...] = ()) -> None:
    """Serve this employee, ask it one question, and print what it does."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question", nargs="?", default="Are Canadian customers able to check out?"
    )
    parser.add_argument("--effort", default=None)
    if harnesses:
        parser.add_argument(
            "--harness",
            choices=harnesses,
            default=None,
            help=f"overrides {identity.name.upper()}_HARNESS for the next ticket",
        )
    args = parser.parse_args()

    if getattr(args, "harness", None):
        # Effective, now that this process is also the one serving: the config
        # is read per ticket, from this environment.
        os.environ[f"{identity.name.upper()}_HARNESS"] = args.harness

    reference = f"watch-{uuid.uuid4().hex[:8]}"
    watcher = Service(f"watch-{identity.name}", max_slots=1)

    @watcher.event(topics.STEP, group=f"watch-{uuid.uuid4().hex[:6]}")
    async def on_step(_: Context, params: Params) -> None:
        """A group of its own, so watching is not stealing.

        One consumer group per subscriber is how the runtime fans an event out.
        A watcher sharing another's group would take half its events and neither
        would notice.
        """
        step = dict(params)
        # The topics carry the whole staff. Without this, a second employee
        # serving in another terminal prints its steps into this trace.
        if step.get("reference") == reference:
            show(step)

    @watcher.once(delay=0)
    async def ask(ctx: Context) -> None:
        print(f"\n  ? {args.question}\n", flush=True)
        reply = await ctx.call(
            identity.investigate,
            ttl=TTL,
            ticket=args.question,
            reference=reference,
            effort=args.effort,
        )
        answer = reply.get("answer") or {}
        print(
            f"\n  = {reply.get('status')} via {reply.get('harness')} "
            f"({reply.get('tool_calls', 0)} calls, run {reply.get('run_id')})"
        )
        for field in _ANSWER:
            if answer.get(field):
                print(f"    {field}: {answer[field]}")
        for finding in answer.get("findings") or []:
            print(f"    - {finding.get('fact')}   [{finding.get('source')}]")
        if reply.get("error"):
            print(f"    error: {reply['error']}")
        print(f"    transcript: {reply.get('transcript')}\n", flush=True)
        # Nothing stops `App.start()`, and the answer is out. `_exit` rather
        # than `sys.exit`: this runs inside a task the runtime would otherwise
        # keep serving.
        await asyncio.sleep(0)
        os._exit(0)

    cfg = load(identity.name)
    app = App(redis=cfg.queue.url, namespace=cfg.queue.namespace)
    # Both halves in one process: the employee that answers and the caller that
    # watches. Nothing is short-circuited by their sharing an App. The call
    # still goes out on a stream and comes back through a reply list, and the
    # events still fan out to a group; the runtime does not know they are
    # neighbours. It only spares you a second terminal.
    app.include(serve(identity))
    app.include(watcher)
    app.start()
