"""Narrating an investigation to a terminal, through the same door as the bus.

`service.BusNarrator` publishes an investigation's events onto Redis. This one
prints them, one JSON object per line, and that is the entire difference: both
are `run.Narrator`, so a run started by hand and a run started by `ctx.call` are
the same investigation narrated to different listeners rather than two code
paths that have to be kept in step.

**The same shape the simulator uses for its journey events**, deliberately, so
once an employee runs inside the stack these lines land in Loki through the same
Alloy pipeline and are queried with the same LogQL.

Not OpenTelemetry, yet. pydantic-ai ships `Agent.instrument_all()` and it is the
right answer for spans and cross-service timing — but traces need a collector and
a trace store, and the stack has Loki and Prometheus, not Tempo. JSON lines cost
nothing and are queryable today; the OTel path stays open and does not conflict.
"""

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class JsonLines:
    """One JSON object per line on stdout, for whoever is tailing it.

    Stateless and frozen: it holds no run, so the fields it is given are the
    whole of what it says. The run id arrives on every event from `run` itself,
    which is why nothing has to be passed in here.

    **stdout is resolved per line**, never bound at construction, so a caller
    that redirects it — a test, a shell pipeline — is not written past.
    """

    async def started(self, **fields: Any) -> None:
        self._say("investigation_started", fields)

    async def step(self, **fields: Any) -> None:
        self._say("step", fields)

    async def finished(self, **fields: Any) -> None:
        self._say("investigation_finished", fields)

    def _say(self, event: str, fields: dict[str, Any]) -> None:
        """One line, and never an exception: a broken trace must not kill a run.

        `default=str` because a step may carry a path or a datetime, and losing
        the line that says what went wrong to a serialisation error is how a
        trace becomes worse than no trace.
        """
        line = {
            "event": event,
            "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            **fields,
        }
        try:
            print(json.dumps(line, default=str), file=sys.stdout, flush=True)
        except Exception as error:  # noqa: BLE001 — defensive, never fatal
            print(f"trace failed for {event}: {error}", file=sys.stderr)
