"""What the technical flows accept on the queue."""

from typing import Any

from pydantic import BaseModel


class ConfigChange(BaseModel):
    """One requested change: which knob, and what to set it to.

    `value=None` means **reset** — drop the override and fall back to the layer
    below. No tunable accepts None as a real value and an absent switch means
    running, so the sentinel is unambiguous for both kinds of key and keeps this
    to one action instead of a set/clear pair.
    """

    key: str
    value: Any = None
