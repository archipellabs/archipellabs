"""Which employees a process mounts, and how it refuses.

The entry point replaced seven byte-identical `app.py` files. What it added is a
choice the deployment makes rather than the image: one container per employee,
or one for all of them, off the same `AGENT_NAME`.
"""

import pytest

from core.main import employed, identity, named


def test_every_role_directory_is_found() -> None:
    """Discovered by walking, not by `pkgutil.iter_modules`.

    These are PEP 420 namespace packages — no `__init__.py`, by the
    repository's convention — and `iter_modules` reports only regular ones. The
    first version used it, returned an empty list, and refused every name it was
    given with "philip is not an employee".
    """
    assert {"angel", "blair", "charlie", "dana", "ethan", "mock", "philip"} <= set(
        employed()
    )


def test_one_name_mounts_one_employee() -> None:
    assert named("philip") == ["philip"]


def test_a_list_mounts_several_in_the_order_given() -> None:
    """Order is kept because the first one named decides which configuration the
    queue is read from."""
    assert named("angel,philip") == ["angel", "philip"]


def test_a_star_mounts_everyone() -> None:
    assert named("*") == employed()


def test_spacing_and_blanks_are_forgiven() -> None:
    assert named(" angel , philip ") == ["angel", "philip"]
    assert named("angel,,philip") == ["angel", "philip"]


def test_a_name_asked_for_twice_is_mounted_once() -> None:
    """Two services of one name would take turns on the same stream, so a ticket
    would reach whichever pulled first and the employee would appear to answer
    half its questions."""
    assert named("angel,philip,angel") == ["angel", "philip"]


def test_an_unknown_name_is_refused_and_says_who_exists() -> None:
    """A name that is merely absent would start nothing and log nothing, and a
    container that exits silently reads exactly like one that is working."""
    with pytest.raises(SystemExit) as refused:
        identity("philipe")

    said = str(refused.value)
    assert "philipe" in said
    assert "philip" in said, "the refusal must name the employees that exist"


def test_a_mounted_identity_answers_to_the_name_it_was_asked_for() -> None:
    """The directory is the name a caller routes on, so the two cannot disagree
    — a mismatch would route tickets to an employee nobody asked for."""
    for name in employed():
        assert identity(name).name == name
        assert identity(name).investigate == f"{name}.investigate"
