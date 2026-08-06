"""The one agreement six employees are held to, in both directions."""

import json

import pytest
from pydantic import ValidationError

from core.brief import JSON_VERDICT
from core.contract import ANSWER_SCHEMA, Answer, Ticket, strict_schema

RETIRED = {
    "detected",
    "diagnosis",
    "root_cause",
    "remediation",
    "confidence",
    "findings",
}
"""The six fields the hand-written schema required, written out rather than
imported: this test exists to catch the derived schema drifting away from them,
and importing the thing under test would make it agree with itself."""


def test_the_derived_schema_requires_exactly_the_six_fields():
    assert set(ANSWER_SCHEMA["required"]) == RETIRED
    assert set(ANSWER_SCHEMA["properties"]) == RETIRED


def test_every_object_is_closed_including_the_nested_one():
    """A loop returning a seventh field must be told, not quietly accepted."""
    assert ANSWER_SCHEMA["additionalProperties"] is False
    findings = ANSWER_SCHEMA["properties"]["findings"]["items"]
    assert findings["additionalProperties"] is False
    assert set(findings["required"]) == {"fact", "source"}


def test_the_two_fields_with_defaults_are_still_required():
    """`findings` and `confidence` carry defaults, so pydantic drops them from
    `required` — and they are exactly the two a hurried answer would omit."""
    assert {"findings", "confidence"} <= set(ANSWER_SCHEMA["required"])


def test_nothing_a_strict_decoder_rejects_survives():
    rendered = json.dumps(ANSWER_SCHEMA)
    assert '"default"' not in rendered
    assert '"title"' not in rendered
    assert "$ref" not in rendered and "$defs" not in rendered


def test_the_descriptions_that_steer_a_model_reach_the_schema():
    """The point of deriving it: one wording, not two kept in step by hand."""
    assert ANSWER_SCHEMA["properties"]["root_cause"]["description"].startswith(
        "What HAPPENED"
    )
    source = ANSWER_SCHEMA["properties"]["findings"]["items"]["properties"]["source"]
    assert source["description"]


def test_the_prose_verdict_names_the_same_fields_as_the_type():
    """`brief.JSON_VERDICT` is a prompt, so it is written by hand rather than
    derived — changing that text would change every campaign's comparability.
    This is what keeps the two from drifting apart anyway."""
    assert {name for name in Answer.model_fields if name in JSON_VERDICT} == set(
        Answer.model_fields
    )


@pytest.mark.parametrize("given", ["high", "High", " HIGH "])
def test_a_confidence_is_read_however_it_was_spelled(given):
    """A loop asked for this word in a prompt is not constrained to it, and
    losing an investigation to a capital letter is the instrument breaking."""
    assert _answer(confidence=given).confidence == "high"


def test_a_confidence_that_is_not_one_of_the_three_is_refused():
    with pytest.raises(ValidationError):
        _answer(confidence="probably")


def test_an_extra_field_is_dropped_rather_than_fatal():
    answered = _answer(elapsed="four minutes")
    assert not hasattr(answered, "elapsed")


def test_a_depth_nothing_knows_is_refused_at_the_edge():
    """Before a workspace, a run directory or a `started` event exist."""
    with pytest.raises(ValidationError, match="effort must be one of"):
        Ticket(ticket="sales look off", effort="ludicrous")


def test_an_unchosen_depth_stays_unchosen():
    assert Ticket(ticket="sales look off").effort is None


def test_a_blank_ticket_is_not_a_ticket():
    with pytest.raises(ValidationError):
        Ticket(ticket="")


def test_strict_schema_closes_a_model_it_has_never_seen():
    """The transform is general, not tailored to `Answer`."""
    schema = strict_schema(Ticket)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(Ticket.model_fields)


def _answer(**overrides):
    return Answer.model_validate(
        {
            "detected": "Canadian checkout stops at delivery.",
            "diagnosis": "No carrier prices the Canadian zone.",
            "root_cause": "The feed lost its CA rows.",
            "remediation": "Restore them and re-import.",
            **overrides,
        }
    )
