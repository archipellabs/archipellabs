"""Run one investigation from a terminal and print what the analyst found.

The same investigation the queue action runs — `core.investigate` is the
shared path, so a run started here and a run started by `ctx.call` produce
comparable transcripts. What differs is only where the narration goes, and even
that goes through one interface: `JsonLines` prints the events, `BusNarrator`
publishes them, and neither changes what the analyst does.

Two streams. **stdout is JSON lines** — the machine-readable trace, same shape as
the simulator's journey events, so it lands in Loki through the same pipeline.
**stderr is the summary you read.** Both reach the terminal when run by hand;
`2>/dev/null | jq` gives one, `>/dev/null` the other.

    uv run python -m src "sales look off today"     # one investigation
    uv run python -m src.app                        # serve the queue instead
"""

import asyncio
import sys

from core import JsonLines, investigate
from core.config import load
from roles.angel.identity import IDENTITY


def _say(line: str) -> None:
    """Human-readable output goes to stderr, so stdout stays pure JSON lines."""
    print(line, file=sys.stderr)


TICKET = "Sales look off today. Can you look into it?"

VERDICT_FIELDS = ("detected", "diagnosis", "root_cause", "remediation")


async def ask(ticket: str) -> int:
    cfg = load(IDENTITY.name)

    missing = [
        name
        for name, value in (
            ("AGENT_API_KEY", cfg.shop.api_key),
            ("MATOMO_AGENT_TOKEN", cfg.matomo.token),
        )
        if not value
    ]
    if missing:
        _say(f"missing credentials: {', '.join(missing)}")
        return 2

    _say(f"model   {cfg.model.name}  ({cfg.model.base_url})")
    _say(f"ticket  {ticket}\n")

    verdict = await investigate(IDENTITY, cfg, ticket, narrator=JsonLines())

    _say(f"run        {verdict['run_id']}")
    _say(f"tool calls {verdict.get('tool_calls', 0)}")
    _say(f"transcript {verdict.get('transcript', '-')}\n")

    # The verdict is nested and the accounting is flat. Together in one
    # dictionary they were the same thing, and a page rendering the answer
    # showed `cache_read_tokens` as a finding.
    answer = verdict.get("answer")
    if verdict["status"] == "completed" and answer:
        for field in VERDICT_FIELDS:
            _say(f"{field:11} {answer[field]}")
        _say(f"{'confidence':11} {answer['confidence']}")
        if answer.get("findings"):
            _say("\nevidence")
            for finding in answer["findings"]:
                _say(f"  - {finding['fact']}   [{finding['source']}]")
        return 0

    # A refusal says why in `error`, exactly as a crash does. Which of the two
    # it was is `status`, and the run record holds the rest.
    _say(f"{verdict['status'].upper()}  {verdict.get('error', '')}")
    return 1


def main() -> int:
    ticket = " ".join(sys.argv[1:]).strip() or TICKET
    return asyncio.run(ask(ticket))


if __name__ == "__main__":
    raise SystemExit(main())
