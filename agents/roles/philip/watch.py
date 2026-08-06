"""Ask Philip something and watch it work.

    uv run python -m src.watch
    uv run python -m src.watch --harness opencode "are Canadian customers able to check out?"

The whole script is `core.watch`, which is the same script for every
employee. What Philip supplies is what Philip is: an identity, and the two loops
it can be driven by.
"""

from core import watch
from roles.philip.identity import IDENTITY, OPENCODE

HARNESSES = ("codex", OPENCODE)

if __name__ == "__main__":
    watch.main(IDENTITY, HARNESSES)
