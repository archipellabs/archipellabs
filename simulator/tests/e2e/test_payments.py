"""Bank-wire settlement against a live PrestaShop (Webservice API). Run on demand:

    uv run pytest tests/e2e/test_payments.py

Accepts up to MAX_PER_PASS waiting orders and leaves them in *Payment accepted*.
"""

import pytest

from src.internal_flows.catalog.client import json_client, xml_client
from src.internal_flows.payments.accept import (
    MAX_PER_PASS,
    accept_bank_wire_payments,
)

pytestmark = pytest.mark.e2e


async def test_waiting_bank_wires_are_accepted():
    """One pass settles a bounded batch and reports what is left.

    An order that stays in "Awaiting bank wire payment" is indistinguishable, in
    every revenue figure the shop can produce, from one that was never placed —
    so this is the step that makes an order count.
    """
    async with json_client() as json_http, xml_client() as xml_http:
        first = await accept_bank_wire_payments(json_http, xml_http)

    assert first["errors"] == []
    # Whatever was waiting, a pass settles it up to the batch ceiling.
    assert len(first["accepted"]) == min(first["waiting"], MAX_PER_PASS)


async def test_accepting_is_idempotent_once_the_backlog_is_clear():
    """Draining, then re-running, must find nothing — the flow selects only orders
    still awaiting payment, so it can run on a timer without re-touching an order
    it already settled."""
    async with json_client() as json_http, xml_client() as xml_http:
        while True:
            summary = await accept_bank_wire_payments(json_http, xml_http)
            assert summary["errors"] == []
            if not summary["accepted"]:
                break

        again = await accept_bank_wire_payments(json_http, xml_http)

    assert again["waiting"] == 0
    assert again["accepted"] == []
