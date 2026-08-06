"""Say how much of the truth you gave.

Charlie's tools are deliberately thin — that is its variable, paired against
Dana, which runs the same loop over Angel's rich ones. Thin means no joins, no
aggregation, no schema walking: one flat read and the rows it returns.

**It does not mean answering as though a page were the whole set.** Charlie's
shop reader used to compute the true row count and then throw it away:

    shown = rows[:MAX_ROWS]
    return {"resource": resource, "returned": len(shown), "rows": shown}

No total, no completeness, no offset — so a saturated read of 25 rows was
indistinguishable from an exhausted one, and no sequence of calls could reach the
number 214. On the conversion-funnel scenario, where the answer turns on an exact
population count, Charlie scored 2 of 18 while Angel got that figure for free on
its first or second call in 14 of 15 transcripts. Its single success bought the
number by hand, cutting the hour into twelve five-minute windows and summing
them: seventeen calls where Angel spent one.

The control that settles it is Charlie's record on the other two scenarios, same
toolkit and same models — six of six on `tracker_blind`, level with Angel on
`carrier_withdrawn`. Conversion funnel is the only one of the three needing an
exact count, and the only one it fails. That was a tool defect wearing the
costume of an agent result, and every campaign that reported it as a harness
difference was reporting this file's absence.

So the rule, and it is about honesty rather than capability:

    returned      how many came back
    offset        where they start
    complete      true | false | unknown
    next_offset   present only when complete is false or unknown
    total         present ONLY when genuinely counted

`unknown` is a first-class answer and the most common one here. A server that
caps a result does not report what it withheld, and inventing a number there
would be the same lie in another costume.
"""

from typing import Any


def window(
    rows: list[Any], *, cap: int, offset: int = 0, server_capped: bool = False
) -> dict[str, Any]:
    """Wrap rows in the completeness envelope.

    `server_capped` says the *caller* asked the remote system to limit the
    result. Whatever came back is then all the server chose to send, and nothing
    here can tell whether more exist, so the honest answer is `unknown` rather
    than a count we would be inventing.

    The case that matters most is the first branch: when **we** did the
    truncating, we hold the whole matched set and the count is genuine. That is
    the number Charlie was discarding.
    """
    shown = rows[:cap]
    envelope: dict[str, Any] = {"returned": len(shown), "offset": offset}

    if len(rows) > cap:
        # We truncated, so we know exactly how many the query matched.
        envelope["complete"] = False
        envelope["total"] = len(rows)
        envelope["next_offset"] = offset + cap
        # Where the final page starts. A resource that cannot be sorted comes
        # back oldest-first, so "what happened lately" lives at the far end and
        # is several deliberate pages away.
        envelope["last_offset"] = ((len(rows) - 1) // cap) * cap
    elif server_capped:
        # The server may have withheld more. The page length is not the query
        # total, so the honest answer is that we do not know.
        envelope["complete"] = "unknown"
        envelope["next_offset"] = offset + len(shown)
    else:
        # Nothing capped this: what came back is everything the query matched.
        envelope["complete"] = True
        envelope["total"] = len(shown)

    envelope["rows"] = shown
    return envelope
