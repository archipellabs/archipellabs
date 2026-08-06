"""Call `ethan.investigate` over the bus and print what came back.

    python -m tests.ethan.e2e.probe "the question"

A separate process, because that is what a caller is. The runtime offers no
one-shot client: `call` needs a node with a reply pump, which means an `App`,
and `App.start()` blocks until interrupted. So the probe is a tiny App whose
only job is one call, and it exits as soon as it has the answer.

Run as a subprocess by the e2e tests rather than imported, so the path under
test is the real one: two processes, a Redis stream between them, the action
claimed by a worker slot, the reply pushed to a reply list. An in-process call
would exercise the harness and call it end to end.
"""

import json
import os
import sys

from runtime import App, Context, Service

TTL = "10m"
"""Generous: an investigation is a model turn, sometimes several minutes. The
caller's own deadline is the outer bound, and a call that expires reports
nothing rather than reporting a failure."""

probe = Service("e2e-probe")


@probe.once(delay=0)
async def ask(ctx: Context) -> None:
    answer = await ctx.call(
        "ethan.investigate",
        ttl=TTL,
        ticket=sys.argv[1],
        reference="e2e",
    )
    print(json.dumps(answer), flush=True)
    # Nothing here can stop `App.start()`, which runs until interrupted. The
    # answer is out; leaving is the point.
    os._exit(0)


if __name__ == "__main__":
    app = App(
        redis=os.getenv("AGENT_REDIS_URL", "redis://localhost:6379/0"),
        namespace=os.getenv("AGENT_NAMESPACE", "sim"),
    )
    app.include(probe)
    app.start()
