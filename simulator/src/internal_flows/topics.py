"""Event types exchanged within the internal flows — the queue contracts.

`Topic` is a `StrEnum`, so a member is a plain `str` everywhere the runtime
expects one (`emit`, `consumes`, stream naming).
"""

from enum import StrEnum


class Topic(StrEnum):
    CATALOG_SYNC = "catalog.sync"
