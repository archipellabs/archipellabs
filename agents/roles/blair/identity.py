"""Who Blair is: a toolbox, and the loop that is written in Python.

Everything else — the ticket, the events, the record, the envelope, the bus mount
— is `core`. What is left here is the part that makes this employee a
distinct one, and against Angel it is exactly one part:

    angel   = our loop  + wide, specific tools
    blair   = our loop  + compact, generic tools    ← the difference is the tools

**No `routable` guard here**, unlike the desk-driven employees: Blair's provider
is built from `cfg.model.base_url` and the key beside it, so the endpoint a
campaign names is the endpoint the run uses.
"""

from core import Identity
from core.harness import pydantic_ai
from roles.blair.agent import TOOLBOX

AGENT = "blair"

IDENTITY = Identity(AGENT, lambda cfg: pydantic_ai.build(cfg, TOOLBOX))
