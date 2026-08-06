"""Run one Blair investigation and print a readable summary to stderr.

The same investigation the queue action runs — `core.investigate` is the
shared path — narrated to a different listener. **stdout is JSON lines** for the
log pipeline, **stderr is the summary you read**.
"""

import asyncio
import sys

from core import JsonLines, investigate
from core.config import load
from roles.blair.identity import IDENTITY

DEFAULT_TICKET = "Something seems wrong. Please investigate."

VERDICT_FIELDS = ("detected", "diagnosis", "root_cause", "remediation")


def _say(text: str) -> None:
    print(text, file=sys.stderr)


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

    # The verdict is nested and the accounting is flat, so a reader rendering
    # the answer cannot show `cache_read_tokens` as a finding.
    answer = verdict.get("answer")
    if verdict["status"] == "completed" and answer:
        for field in VERDICT_FIELDS:
            _say(f"{field:11} {answer[field]}")
        _say(f"{'confidence':11} {answer['confidence']}")
        for finding in answer.get("findings", []):
            _say(f"  - {finding['fact']} [{finding['source']}]")
        return 0
    _say(f"{verdict['status'].upper()}  {verdict.get('error', '')}")
    return 1


def main() -> int:
    ticket = " ".join(sys.argv[1:]).strip() or DEFAULT_TICKET
    return asyncio.run(ask(ticket))


if __name__ == "__main__":
    raise SystemExit(main())
