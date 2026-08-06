"""Who Ethan is: a desk, and a choice of two loops.

Everything else — the ticket, the events, the record, the envelope, the bus
mount — is `core`. What is left here is the part that makes this employee a
distinct one: a directory of skills and API documentation, and the fact that it
can be driven by either of two CLIs so the loop stays a variable under test.

Ethan's desk is deliberately narrower than Philip's — it carries no workspace
analysis skill — and that difference is the experiment. It lives in `desk/`,
which is data, so this file is the same file twice on purpose.
"""

import pathlib

from core import Config, Harness, Identity
from core.harness import codex, opencode_cli
from core.harness.desk import Desk

AGENT = "ethan"

DESK = Desk(root=pathlib.Path(__file__).resolve().parent / "desk")
"""The skills and the API contract, laid out in the workspace before each run."""

CODEX, OPENCODE = "codex", "opencode"

LOOPS = {CODEX: codex.build, OPENCODE: opencode_cli.build}
"""The loops Ethan can be driven by, and the only place that knows there are two.

A mapping rather than an `if`, so an unrecognised name is refused instead of
falling through to whichever branch happens to be last. `ETHAN_HARNESS=claude`
under a fall-through runs codex and reports a row labelled `claude` — the same
failure the `ROUTABLE` guard below exists to prevent, one level up."""

ROUTABLE = "api.openai.com"
"""The only host a campaign's `--base-url` can mean here.

codex reaches a model through its own provider configuration and ignores a base
URL passed from outside, so `--models gemma` would run against whatever codex is
pointed at and return a row labelled `gemma`. The analysts that build an HTTP
client from that URL genuinely honour it. Refusing is the difference between a
missing cell and a wrong one, and this lab has already published a figure it had
to retract for less.

Checked for both loops rather than only for codex: opencode is handed a provider
configuration of its own too, so neither is known to honour an outside URL, and
narrowing a guard while moving it is how a guard stops guarding.
"""


def routable(config: Config) -> None:
    """Refuse a base URL this employee cannot actually honour.

    Called from the campaign entry point only, and not from `build`. A campaign
    is the one caller that *names* an endpoint and then labels a row with it; a
    ticket arriving on the bus names no endpoint at all, so the deployment's own
    default applies and nothing is being mislabelled. Guarding `build` instead
    refused every run these employees have ever served, which is how a guard
    stops being one.
    """
    if ROUTABLE not in (config.model.base_url or ""):
        raise ValueError(
            f"{AGENT} reaches models through a CLI that ignores "
            f"--base-url {config.model.base_url!r}. Compare on a hosted model "
            f"(luna, terra, sol) or leave {AGENT} out of this campaign."
        )


def build(config: Config) -> Harness:
    """The loop this ticket runs on."""
    chosen = config.harness or CODEX
    if chosen not in LOOPS:
        raise ValueError(
            f"{AGENT.upper()}_HARNESS must be one of "
            f"{', '.join(LOOPS)}, not {chosen!r}"
        )
    return LOOPS[chosen](config, DESK)


IDENTITY = Identity(AGENT, build)
