"""What an employee answers to, and what it says while it works.

One **action** and three **events**, and that distinction decides which names
have to be unique per employee.

**The action carries the employee's name** — `angel.investigate`. An action has
exactly one correct executant, so the runtime gives every consumer of a name one
shared group. Two containers both serving `analyst.investigate` would therefore
not each receive every ticket: they would **split them between themselves**,
silently, and each would look like it was working normally. Nothing local can
detect that — no registry exists — so the name is the only defence.

**The events do not.** They fan out, one consumer group per subscriber, so a
portal tailing `analyst.step` sees every employee at once and keeps seeing them
when a new one is hired. Who emitted is a *field*, not a topic: making the
events per-agent would force every subscriber to be updated for each hire, and
buy nothing, because nobody is waiting on an event and two subscribers to the
same event do not compete.
"""

STARTED = "analyst.started"
"""An investigation began. Shared across employees — see the module docstring."""

STEP = "analyst.step"
"""One tool call or result, live."""

FINISHED = "analyst.finished"
"""A verdict, or a crash. Either way the run is over."""


# The action's name is **not** here, and that absence is the point. It is
# `Identity.investigate`, because it is derived from the employee's name and the
# name is what `Identity` already is — and already validates. A second object
# holding a copy of the name meant the invariant that keeps one employee from
# claiming another's action was written, and had to stay right, in two places.
#
# The events stay module constants for the reason above: they are not per
# employee, and hanging them off an object that is would suggest otherwise.
