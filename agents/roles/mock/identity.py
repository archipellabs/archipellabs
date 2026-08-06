"""Who this employee is: nobody, on purpose.

Every other agent's identity is a toolset or a desk — the thing that makes it
worth asking. This one has neither, and that is the point: what it exercises is
everything *around* a loop, which until now could only be tested by spending a
model call and waiting minutes.

The two knobs are read from this process's own environment rather than from the
shared `Config`. A step count is nobody else's business, and putting it in the
configuration object would make five real employees carry a field only this one
reads.
"""

import os

from core import Identity
from core.mock import build

STEPS = int(os.getenv("MOCK_STEPS", "6"))
"""How many steps to emit. The script cycles, so more than its length repeats."""

DELAY_S = float(os.getenv("MOCK_DELAY_S", "0"))
"""Seconds between steps.

Zero by default, which is right for a test. Set it to two or three to watch a
live stream arrive at a pace a person can read — the reason this employee exists
in a deployment as well as in a test suite."""

ERROR = os.getenv("MOCK_ERROR") or None
"""Set to make every run fail, for exercising the path nobody wants to stage."""

IDENTITY = Identity("mock", build(steps=STEPS, delay_s=DELAY_S, error=ERROR))
