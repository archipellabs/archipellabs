"""A small, uniform contract for partial answers."""

from typing import Any

Completeness = bool | str


def page(
    rows: list[Any],
    *,
    limit: int,
    offset: int = 0,
    total: int | None = None,
    complete: Completeness | None = None,
) -> dict[str, Any]:
    """Return one page and state what is known about the unseen remainder."""
    limit = max(1, min(limit, 100))
    shown = rows[:limit]
    result: dict[str, Any] = {
        "rows": shown,
        "returned": len(shown),
        "offset": max(0, offset),
    }
    if total is not None:
        result["total"] = total
        known_complete = offset + len(shown) >= total
        result["complete"] = known_complete if complete is None else complete
        if not known_complete:
            result["next_offset"] = offset + len(shown)
            result["last_offset"] = ((total - 1) // limit) * limit if total else 0
        return result

    state: Completeness = "unknown" if complete is None else complete
    result["complete"] = state
    if state is not True:
        result["next_offset"] = offset + len(shown)
    return result
