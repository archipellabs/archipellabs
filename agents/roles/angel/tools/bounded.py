"""One contract for every bounded answer: say how much of the truth you gave.

Three tools had grown the same defect independently. `total` meant "rows I am
returning", so a read with `limit=3` answered `total: 3` against a table of 709.
The feed cut files at 20 KB with no marker. Loki stopped at 5000 lines and said
nothing. In each case a partial answer was indistinguishable from a complete one.

That is the session's recurring bug in a third costume — the first two were a
sort that returned `[]` instead of an error, and a Matomo failure delivered with
HTTP 200. All three let an investigator conclude *"this does not exist"* from
*"I did not give you all of it"*, and one of them fabricated a root cause. If the
carrier feed were 20 KB and the Canadian row fell past the cut, the tool would
manufacture the very incident it was asked to explain.

So: no bounded output may imply completeness it cannot demonstrate.

    returned      how many came back
    offset        where they start
    complete      true | false | unknown
    next_offset   present only when complete is false or unknown
    total         present ONLY when genuinely counted

`unknown` is a first-class answer and the most common one. A server that caps a
result server-side does not report what it withheld, and inventing a number there
would be the same lie in a fourth costume.
"""

from typing import Any


def window(
    rows: list[Any],
    *,
    cap: int,
    offset: int = 0,
    server_capped: bool = False,
    matched: int | None = None,
) -> dict[str, Any]:
    """Wrap rows in the completeness envelope.

    `server_capped` says the *caller* asked the remote system to limit the
    result — a `limit` or `filter_limit`. Whatever came back is then all the
    server chose to send, and nothing here can tell whether more exist, so the
    honest answer is `unknown` rather than a count we would be inventing.

    `matched` is how many rows the query really matched, for the case where the
    caller holds the whole set and has already sliced it — a client-side sort
    orders all 709 rows and hands back 5. Without it that answer would report
    `complete: true, total: 5`, which is this module's founding lie in yet
    another costume; with it the count is genuine, because it was counted here.
    """
    shown = rows[:cap]
    envelope: dict[str, Any] = {"returned": len(shown), "offset": offset}

    if matched is not None:
        envelope["total"] = matched
        seen_through = offset + len(shown)
        envelope["complete"] = seen_through >= matched
        if not envelope["complete"]:
            envelope["next_offset"] = seen_through
            envelope["last_offset"] = ((matched - 1) // cap) * cap
        envelope["rows"] = shown
        return envelope

    if server_capped:
        # The server may have withheld more rows. The page length is not the
        # query total, so the honest answer is unknown.
        #
        # **Checked FIRST, and that order is the whole point.** It used to come
        # second, so a capped read that happened to return more rows than one
        # page fell into the branch below and reported `total` — a count of what
        # this page brought back, presented as the number the query matched. 100
        # rows from a server that stopped at 100 answered `total: 100` against a
        # table of 709. That is this module's founding lie in the fourth
        # costume, inside the module written to retire the first three: holding
        # more rows than fit on a page says nothing about how many were never
        # sent.
        envelope["complete"] = "unknown"
        envelope["next_offset"] = offset + len(shown)
    elif len(rows) > cap:
        # We did the truncating, so we know exactly how many the query matched.
        envelope["complete"] = False
        envelope["total"] = len(rows)
        envelope["next_offset"] = offset + cap
        # Where the final page starts. A resource that cannot be sorted returns
        # oldest-first, so "what happened lately" lives at the far end and is
        # several deliberate pages away. Two runs concluded that orders had
        # stopped, and one invented replica lag to explain a gap that was only
        # the horizon of page one. `next_offset` alone says "there is more"; this
        # says how to get to the other end of it in a single hop.
        envelope["last_offset"] = ((len(rows) - 1) // cap) * cap
    else:
        # Nothing capped this: what came back is everything the query matched.
        envelope["complete"] = True
        envelope["total"] = len(shown)

    envelope["rows"] = shown
    return envelope
