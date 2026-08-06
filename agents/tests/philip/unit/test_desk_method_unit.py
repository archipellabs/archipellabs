"""The desk must make analysis the path of least resistance, not merely allow it.

This is what separates Philip from Ethan, and it is the whole hypothesis under
test. Ethan's brief was given a paragraph saying its shell was for analysis, that
`$PYTHON` was real, and that relating records should be computed rather than
read. It was present in every run, unavoidable, and it changed nothing
measurable: shop calls per run fell from 3.0 to 1.8, and **zero of six runs
wrote a line of code**.

The conclusion drawn from that is that a run copies the shape of the commands it
is shown, not the advice it is given. So Philip's skills were rewritten so that
every worked fetch lands in a file and hands back a status line instead of a
body — leaving no page of rows to read by eye in the first place.

That is a property of sixty-odd examples across five files, which is exactly the
kind of property that decays one convenient edit at a time. These tests are the
ratchet. They do not check that the desk is *good*; they check that it still
makes the same bet, so that a campaign comparing Philip to Ethan is still
comparing the thing it was built to compare.
"""

import pathlib
import re

import pytest

from core.harness import desk
from roles.philip.identity import DESK

SKILLS = sorted((DESK.root / "skills").glob("*/SKILL.md"))

CURL_BLOCK = re.compile(r"```[a-z]*\n((?:.|\n)*?)```")

KEEPS_THE_BODY = (
    "-o data/",
    "| tee data/",
    "-o data/NAME",
    "-o data/matomo_METHOD.json",
)
"""Writing to the workspace, or branching a copy there on the way past."""

PROBES = (
    "-o /dev/null",
    "[nope]",
)
"""The documented exceptions, and both earn it.

`-o /dev/null` is the connection check: it asks for a status and deliberately
wants no body. The `[nope]` calls provoke a field-name error on purpose, and
their answer *is* the message that comes back, so sending it to a file would
hide the only thing they are for.
"""


def fetches(skill: pathlib.Path) -> list[str]:
    """Every fenced block that calls a system with curl."""
    return [
        block
        for block in CURL_BLOCK.findall(skill.read_text())
        if any(line.strip().startswith("curl ") for line in block.splitlines())
    ]


@pytest.mark.parametrize("skill", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_every_worked_fetch_lands_in_the_workspace(skill: pathlib.Path) -> None:
    stdout_only = [
        block
        for block in fetches(skill)
        if not any(mark in block for mark in KEEPS_THE_BODY)
        and not any(probe in block for probe in PROBES)
    ]

    assert not stdout_only, (
        f"{skill.parent.name} has {len(stdout_only)} example(s) that print the "
        f"response instead of saving it, starting with: "
        f"{stdout_only[0].strip().splitlines()[0][:120]}. An example that ends "
        "at stdout is an example that teaches reading rows by eye."
    )


@pytest.mark.parametrize("skill", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_every_fetch_reports_the_status_it_no_longer_prints(
    skill: pathlib.Path,
) -> None:
    """With the body in a file, `-w` is the only place a 401 can appear.

    A fetch that writes to `data/` and drops the receipt is worse than the
    version this replaced: it is silent on failure rather than merely verbose on
    success.
    """
    silent = [
        block
        for block in fetches(skill)
        if "-o data/" in block and "%{http_code}" not in block
    ]

    assert not silent, (
        f"{skill.parent.name} saves a response without printing its status: "
        f"{silent[0].strip().splitlines()[0][:120]}"
    )


def test_the_analysis_skill_shows_a_script_being_written_and_run() -> None:
    """The one skill whose subject is method rather than a system.

    A worked example that stops at "you could write a script" is the advice that
    already failed. It has to show the file being created, run with the right
    interpreter, and checked — otherwise there is nothing to copy.
    """
    skill = DESK.root / "skills" / "workspace-analysis" / "SKILL.md"
    text = skill.read_text()

    assert "cat > " in text and "<<'PY'" in text, "no script is written"
    assert '"$PYTHON" ' in text, "no script is run, or is run with the wrong python"
    assert "UNMATCHED" in text, "the join is never checked for having matched"


def test_the_brief_states_the_loop_rather_than_permitting_it() -> None:
    """Ethan's brief said the shell *is for* analysis. Philip's says what to do.

    The three nouns below are the loop: where responses go, what computes over
    them, and the skill that works it end to end. A brief missing any of them has
    drifted back to permission.
    """
    brief = desk.brief(DESK)

    for token in ("data/", '"$PYTHON"', "workspace-analysis"):
        assert token in brief, f"the brief no longer names {token}"


def test_the_workspace_has_somewhere_to_put_things(tmp_path: pathlib.Path) -> None:
    """`curl -o data/x` into a missing directory fails as a local file error in
    the middle of a remote call, which reads as an unreachable system."""
    desk.prepare(DESK, tmp_path)

    assert (tmp_path / desk.DATA).is_dir()
