"""Do the skills tell the truth about the running systems?

A third kind of test, and the cheapest of the three.

The unit tests never touch a system. The functional tests ask an agent to use a
skill, which costs a model turn and ninety seconds each. These take the commands
**out of the skill files themselves** and run them, so a documented command that
cannot work fails in seconds with no model involved.

That is the failure this catches, and it has happened twice in one afternoon.
A skill said to select logs with `{container="prestashop"}`; this deployment has
no `container` label, so every query returned empty and an investigation read
that as "the service logged nothing". Another told the agent to use `sshpass`
and `curl --sftp`, neither of which exists on this machine, and the run reported
that the feed credentials were unavailable, which was true of nothing.

Both were documentation written from a manual rather than from the environment.
The skill files are the contract between the lab and its analysts, and a
contract nobody checks is a set of confident sentences.

Marked `contract`, deselected by default, run with `-m contract`.
"""

import os
import pathlib
import re
import subprocess

import pytest

from core.config import load
from core.harness import desk
from roles.ethan.identity import DESK

pytestmark = pytest.mark.contract

SKILLS = DESK.root / "skills"

RUNNABLE = ("curl ", '"$PYTHON" ', "$PYTHON ")
"""A fenced line is executed when it starts one of these.

Deliberately narrow. A block showing a LogQL expression or a JSON payload is
documentation, not a command, and running it would fail for reasons that say
nothing about the system."""

ADDRESSED = re.compile(r"https?://|_URL|index\.php")
"""A command has to name something to call.

A skill may state an invariant prefix once (`curl -sS -g --cacert ... -u ...`)
so the worked examples below it stay short. That is a fragment, and running it
gets `curl: (2) no URL specified`, which says nothing about the system."""

PLACEHOLDER = re.compile(r"<[a-z_]+>")
"""A usage line such as `feed.py head <path> [n]`. Documentation of a signature,
not an invocation: the shell reads `<path>` as a redirection and fails for a
reason that has nothing to do with the system being documented."""

BROKEN = re.compile(
    r"could not resolve|connection refused|command not found|no such file"
    r"|modulenotfounderror|401 unauthorized|403 forbidden|404 not found"
    r"|\"status\"\s*:\s*\"error\"|<title>error",
    re.I,
)
"""What a working system does not say back.

Matched against output rather than relying on exit status alone: `curl` exits 0
on an HTTP 404, and a REST API that answers `{"status":"error"}` with a 200 is
exactly the kind of thing these skills exist to warn about."""


def commands(skill: pathlib.Path) -> list[str]:
    """Every runnable line inside a fenced block of a SKILL.md."""
    text = skill.read_text()
    found: list[str] = []
    for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S):
        # Join continuations so a multi-line curl runs as one command.
        joined = block.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if not line.startswith(RUNNABLE):
                continue
            # `<path>` and friends are usage templates, not commands. Running
            # one fails on shell redirection and says nothing about the system.
            if PLACEHOLDER.search(line):
                continue
            # curl must name something to call; a script invocation need not.
            if line.startswith("curl ") and not ADDRESSED.search(line):
                continue
            found.append(line)
    return found


@pytest.fixture(scope="session")
def workdir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """A prepared desk, so the `.agents/skills/...` paths in commands resolve."""
    root = tmp_path_factory.mktemp("desk")
    desk.prepare(DESK, root)
    return root


@pytest.fixture(scope="session", autouse=True)
def company_is_reachable() -> None:
    """Skip rather than fail when the stack is down.

    A red suite because Docker is not running says nothing about the skills, and
    a test that cannot tell those apart teaches you to ignore it.
    """
    if not os.environ.get("SHOP_API_URL"):
        pytest.skip("no company in the environment (source the agent's .env)")


def each_command() -> list[tuple[str, str]]:
    return [
        (skill.parent.name, command)
        for skill in sorted(SKILLS.glob("*/SKILL.md"))
        for command in commands(skill)
    ]


@pytest.mark.parametrize(
    "skill,command",
    each_command(),
    ids=[f"{name}:{c[:40]}" for name, c in each_command()],
)
def test_a_documented_command_runs(
    skill: str, command: str, workdir: pathlib.Path
) -> None:
    """Every command a skill offers must work against the real system."""
    # Built from the resolved configuration, like the drivers do: the
    # deployment names the shop's key `AGENT_API_KEY` and the skills go on
    # saying `$SHOP_API_KEY`. This is where the two meet.
    env = {**os.environ, **desk.company_env(DESK, load("ethan"))}
    done = subprocess.run(
        ["bash", "-c", command],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = f"{done.stdout}\n{done.stderr}"

    assert done.returncode == 0, f"exited {done.returncode}: {output[-400:]}"
    assert not BROKEN.search(output), f"{skill} documents a failing command: {output[-400:]}"


def test_every_skill_offers_at_least_one_command() -> None:
    """A skill with nothing runnable in it is prose, and prose cannot be checked.

    This is the guard on the guard: without it, deleting the code fences from a
    skill would make every test above pass by having nothing to run.
    """
    for skill in sorted(SKILLS.glob("*/SKILL.md")):
        assert commands(skill), f"{skill.parent.name} has no runnable command"


def test_the_interpreter_the_skills_name_has_what_they_import() -> None:
    """`$PYTHON` is what a skill's scripts must be run with. The system one is
    not it, and under that one the ERP script dies on ModuleNotFoundError."""
    done = subprocess.run(
        [str(desk.interpreter()), "-c", "import paramiko"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert done.returncode == 0, done.stderr
