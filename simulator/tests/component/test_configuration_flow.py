"""The configuration control plane over a fake Redis, end to end.

A change is put on the queue the way a portal would put it, claimed off the
stream, validated by the action's `params=` model, and applied — with a real
`SwitchBoard` behind the context, so a flow pause lands in the registry every
worker actually reads. Hermetic: no real Redis, no browser.

The unit tests cover the routing rules; this covers the wiring between them —
that the topic resolves to a stream someone is listening on, that the payload
survives the round trip, and that a pause is visible to a *different* switchboard
afterwards, which is the whole point of putting it in Redis.
"""

import pytest
from fakeredis.aioredis import FakeRedis
from runtime.broker import Delivery
from runtime.context import RuntimeContext
from runtime.redis_io import RedisBroker
from runtime.switches import SwitchBoard

from src.technical_flows.configuration import actions as actions_module
from src.technical_flows.contracts import ConfigChange
from src.technical_flows.topics import Topic

REGISTRATION = next(
    r for r in actions_module.service.consumers if r.name == Topic.CONFIG_APPLY
)


@pytest.fixture
async def broker():
    broker = RedisBroker(FakeRedis(decode_responses=True))
    await broker.ensure_group(
        REGISTRATION.stream, REGISTRATION.group, start=REGISTRATION.start
    )
    try:
        yield broker
    finally:
        await broker.aclose()


async def _apply_over_the_queue(broker, switches: SwitchBoard, **change) -> dict:
    """Put one change on the stream, claim it, and run the handler on it."""
    caller = RuntimeContext(broker)
    await caller.dispatch(Topic.CONFIG_APPLY, **change)

    messages = await broker.claim(
        REGISTRATION.stream, REGISTRATION.group, consumer="c1", count=10, block_ms=50
    )
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, Delivery)

    # The runtime validates against `params=` before the handler in production;
    # standing in for it here also asserts the payload survived the round trip.
    handler_ctx = RuntimeContext(broker, switches=switches)
    result = await actions_module.apply(
        handler_ctx, ConfigChange.model_validate(message.params)
    )
    await broker.ack(REGISTRATION.stream, REGISTRATION.group, message.id)
    return result


async def test_a_pause_sent_over_the_queue_reaches_the_switch_registry(broker):
    switches = SwitchBoard(broker)

    result = await _apply_over_the_queue(
        broker, switches, key="customer-arrivals", value=False
    )

    assert result == {"key": "customer-arrivals", "kind": "flow", "running": False}
    assert switches.is_enabled("customer-arrivals") is False


async def test_a_pause_is_visible_to_a_switchboard_that_did_not_make_it(broker):
    """The reason a pause goes to Redis rather than into the handler's memory.

    Every worker holds its own snapshot; a change made in one process has to
    reach the others, or pausing a flow would only pause the one that was asked.
    """
    await _apply_over_the_queue(
        broker, SwitchBoard(broker), key="stock-refill", value=False
    )

    elsewhere = SwitchBoard(broker)
    await elsewhere.refresh()

    assert elsewhere.is_enabled("stock-refill") is False


async def test_resuming_over_the_queue_clears_the_pause(broker):
    switches = SwitchBoard(broker)
    await _apply_over_the_queue(broker, switches, key="catalog-doctor", value=False)

    await _apply_over_the_queue(broker, switches, key="catalog-doctor", value=True)

    assert switches.is_enabled("catalog-doctor") is True


async def test_the_master_switch_covers_what_its_service_registers(broker):
    """Pausing a service name pauses everything under it.

    `is_enabled` takes the whole chain — service and registration — so a caller
    that knows only the flow name gets the coarse lever without having to learn
    which registration ids live inside it.
    """
    switches = SwitchBoard(broker)

    await _apply_over_the_queue(broker, switches, key="catalog", value=False)

    assert switches.is_enabled("catalog", "catalog.sync") is False
