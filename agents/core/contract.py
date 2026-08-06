"""What an employee accepts, and what it must hand back.

Both halves in one module because they are one agreement. A caller sends a
`Ticket` and receives an `Answer`; anything that changes one without the other
breaks the pair.

**One shape for every employee, deliberately.** Two analysts accepting different
tickets could not be compared on the same question, and the campaign that thought
it was comparing loops would be comparing request shapes. The same argument holds
on the way out, and it has already been paid for once: one lineage answered with
`summary / diagnosis / confidence` while the others answered with the six fields
below, and a campaign billed as comparing two architectures of access was also
comparing two answer contracts — the weaker of which can be satisfied without
naming a person, a market or a fix. Five runs closed on "no customer-facing
outage is evident", a complete answer under the old shape and an empty one under
this.

**The schema is derived, never written twice.** The loops that cannot enforce a
type need JSON Schema; the loop that can needs a pydantic model. `strict_schema`
makes the second from the first, so the descriptions that steer a model live in
exactly one place. They did not, until now: a hand-written copy carried a
docstring admitting it was kept in step with these fields by hand.
"""

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.config import checked_effort


class Ticket(BaseModel):
    """A request, in the words a colleague would use.

    The question itself is deliberately just prose. Handing the analyst a
    structured `market=CA, symptom=checkout_failure` would be handing it the
    answer's shape, which is a mistake the system prompt has already made once.

    The rest is not about the question but about who answers it and how hard —
    knobs a caller may set and would otherwise have to redeploy an employee to
    change.

    Validated by the runtime before the handler runs, so a malformed request is
    rejected at the edge rather than halfway through the work.
    """

    ticket: str = Field(
        min_length=1, description="What someone noticed, as they would say it."
    )
    reference: str | None = Field(
        default=None,
        description="Caller's own id for this request, echoed back untouched on "
        "every event so a narration can be matched to what asked for it.",
    )
    model: str | None = Field(
        default=None,
        description="Which model answers this one ticket. Unset runs on whatever "
        "the environment configured.",
    )
    effort: str | None = Field(
        default=None,
        description="How hard that model deliberates on this one ticket. Unset "
        "runs on whatever the environment configured.",
    )

    @field_validator("effort")
    @classmethod
    def _a_depth_something_knows(cls, effort: str | None) -> str | None:
        """Refuse an unknown depth here, where refusing still costs nothing.

        At the edge like every other malformed field: the runtime answers the
        caller `ParamsInvalid` before the handler runs, so a typo never becomes a
        prepared workspace, a `started` event and a run directory holding a
        failure that reads like the model's. Passed through instead, it arrives
        as a provider's 400 several seconds in and reports itself as a crash.
        """
        return None if effort is None else checked_effort(effort)


class Finding(BaseModel):
    """One checked fact, with where it came from."""

    fact: str = Field(description="What was observed, concretely and with numbers.")
    source: str = Field(description="Which tool or system the fact came from.")


class Answer(BaseModel):
    """The verdict every loop must produce, whatever loop produced it.

    `extra="ignore"` because a loop asked for this shape in a prompt rather than
    held to it by a type will sometimes add a field. Dropping the extra and
    keeping the answer is better than refusing an investigation over a key nobody
    needed.
    """

    model_config = ConfigDict(extra="ignore")

    detected: str = Field(
        description="What is wrong, in business terms. 'Nothing is wrong' is a "
        "valid answer if the evidence says so."
    )
    diagnosis: str = Field(
        description="The mechanism: which part of the system produces that symptom."
    )
    root_cause: str = Field(
        description="What HAPPENED to put the system in that state — the change, "
        "who or what made it, and when, as far as the evidence shows. Tell it as "
        "a sequence: what was true before, what changed, what that broke. Say "
        "plainly if it could not be established rather than guessing."
    )
    remediation: str = Field(
        description="The concrete action that would fix it — which system, which "
        "file or setting, changed to what. Say if it needs someone with access "
        "you do not have. Not 'investigate further'."
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="The facts the answer rests on, each with where it came from.",
    )
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def _however_it_was_spelled(cls, value: Any) -> Any:
        """`High` and `HIGH` are the same confidence as `high`.

        A loop that returns prose is being asked for this word rather than
        constrained to it, and losing a whole investigation to a capital letter
        would be the instrument breaking, not the analyst.
        """
        return value.strip().lower() if isinstance(value, str) else value


class Refusal(BaseModel):
    """The analyst looked and could not answer.

    A different outcome from a crash, and worth keeping distinct: one is the
    employee reasoning correctly about insufficient evidence, the other is the
    loop falling over. Scored as the same zero, the lab could not tell an honest
    "I could not establish it" from a broken harness.
    """

    error: str
    checked: list[str] = Field(default_factory=list)


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON Schema a strict decoder will accept, derived from the model.

    Four transforms, and each one is a reason the hand-written copy existed:

    * **`$defs` inlined.** Nested models become a `$ref`, which reads as
      indirection in a file whose whole job is to be read by a model.
    * **`additionalProperties: false` everywhere**, recursively and through
      array items. Without it the loop may return a seventh field and be told it
      was fine.
    * **`required` lists every property.** Pydantic omits anything with a
      default, which here is exactly `findings` and `confidence` — the two a
      hurried answer would drop, and the two worth insisting on.
    * **`default` and `title` stripped.** Strict mode rejects `default` outright;
      `title` is noise generated from the field name.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})
    # `_resolve` walks nodes of every JSON type, so it is honestly `Any`. A
    # model's own schema is always the object at the top of that walk.
    return cast(dict[str, Any], _resolve(schema, defs))


def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    """One node of a JSON Schema, inlined and tightened."""
    if isinstance(node, list):
        return [_resolve(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if ref := node.get("$ref"):
        # `#/$defs/Finding` — the only form pydantic emits for a nested model.
        # Merged with its siblings so a `description` written beside the ref is
        # not lost when the definition replaces it.
        target = defs[str(ref).rsplit("/", 1)[-1]]
        node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}

    resolved = {
        key: _resolve(value, defs)
        for key, value in node.items()
        if key not in ("default", "title")
    }
    if resolved.get("type") == "object" and "properties" in resolved:
        resolved["additionalProperties"] = False
        resolved["required"] = list(resolved["properties"])
    return resolved


ANSWER_SCHEMA: dict[str, Any] = strict_schema(Answer)
"""The verdict as JSON Schema, for the loops that cannot be given a type.

Codex enforces it natively through `--output-schema`; opencode is asked for it in
the prompt and checked on the way out by `Answer.model_validate`.
"""
