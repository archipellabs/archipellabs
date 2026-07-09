import logging

from src.services.observability.service import FlowTrace


def test_emit_tags_records_with_flow_id_and_keeps_them():
    trace = FlowTrace("a_test")
    first = trace.emit("step_one", n=1)
    trace.emit("step_two", ok=True)

    assert first["flow_id"] == "a_test"
    assert first["event"] == "step_one"
    assert first["n"] == 1
    assert [e["event"] for e in trace.events] == ["step_one", "step_two"]
    assert all(e["flow_id"] == "a_test" for e in trace.events)


def test_emit_logs_a_greppable_line(caplog):
    trace = FlowTrace("a_grep")
    with caplog.at_level(logging.INFO, logger="flow"):
        trace.emit("hello", x=42)

    assert any(
        "a_grep" in rec.message and "hello" in rec.message for rec in caplog.records
    )
