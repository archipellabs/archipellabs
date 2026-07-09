"""Flow tracing — a tiny technical helper to follow one flow in the logs.

Create a `FlowTrace` with a flow id, then `emit(event, **fields)` at each step.
Every step is a JSON record carrying the flow id, logged under the "flow" logger,
so `grep <flow_id>` pulls one flow's whole trace out of the logs (and
`grep <event>` slices by step). The records are also kept in memory (`.events`)
for callers that want to summarise a run.

Deliberately dumb: no domain knowledge, no backend, no singleton — just an id and
a dict, made greppable. Richer sinks (metrics, persistence) are a separate concern
for later.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("flow")


class FlowTrace:
    def __init__(self, flow_id: str) -> None:
        self.flow_id = flow_id
        self.events: list[dict[str, Any]] = []

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "flow_id": self.flow_id,
            "event": event,
            "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            **fields,
        }
        self.events.append(record)
        log.info(json.dumps(record, default=str))
        return record
