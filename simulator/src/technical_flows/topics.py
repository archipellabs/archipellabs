"""Queue contracts of the technical flows — how the simulator is operated.

A third kind of flow, beside the other two. `external_flows` simulate what
happens to the company from outside (customers arriving, browsing, buying).
`internal_flows` are the company's own back office (catalogue, stock, payments).
These are neither: they act on the **simulator itself** — the levers that change
how it runs, exposed over the queue so an operator, a portal or an agent can
pull them without a deploy and without a web server.

Keeping them apart matters for more than tidiness. A technical flow is out of
universe: it is not something TimberWorks does, so it must never appear in the
company's own data, and nothing modelling the business should import from here.

`Topic` is a `StrEnum`, so a member is a plain `str` everywhere the runtime
expects one (`call`, `dispatch`, `action`, stream naming).
"""

from enum import StrEnum


class Topic(StrEnum):
    CONFIG_APPLY = "config.apply"
    CONFIG_DESCRIBE = "config.describe"
