"""The technical mode every simulated employee shares.

An employee is two things this package does not have: a **toolset** and a
**brief's worth of judgement about where to look**. Everything else — how a
ticket arrives, how a loop is driven, how its steps reach a subscriber, what an
answer must contain, what a run leaves behind — is the same job six times over,
and lives here.

The whole surface an agent needs is re-exported below. An agent that reaches past
it into a submodule is reaching for machinery, which is a sign the seam is in the
wrong place rather than a reason to widen it.

Deliberately absent: **tools, and the loop's own opinions**. Those are what an
employee *is*, and sharing them would leave nothing to compare.
"""

from core.config import Config, checked_effort, load
from core.contract import (
    ANSWER_SCHEMA,
    Answer,
    Finding,
    Refusal,
    Ticket,
    strict_schema,
)
from core.harness.base import (
    Harness,
    Identity,
    Kind,
    Outcome,
    Step,
    Usage,
)
from core.narrate import JsonLines
from core.run import Narrator, as_event, investigate

# `serve` is deliberately NOT re-exported. It is the only thing here that needs a
# bus, and the campaign path runs an investigation without one — importing this
# package should not require a broker to exist. An agent mounting itself reaches
# for `core.service` by name, which is one line and says what it costs.

__all__ = [
    "ANSWER_SCHEMA",
    "Answer",
    "Config",
    "Finding",
    "Harness",
    "Identity",
    "JsonLines",
    "Kind",
    "Narrator",
    "Outcome",
    "Refusal",
    "Step",
    "Ticket",
    "Usage",
    "as_event",
    "checked_effort",
    "investigate",
    "load",
    "strict_schema",
]
