"""The working directory a run is given, laid out before the loop starts.

The subprocess harnesses run in a fresh scratch directory. On its own that
directory is empty, and an empty directory is an employee with no desk: the
skills sit in the employee's own package, and codex looks for them in
`.agents/skills` **relative to where it runs**.

So the desk is assembled per run: the skills copied in, an `AGENTS.md` written
at the root, and the company's credentials handed to the process. That is the
whole of what the role receives, in one place, which is exactly what the next
experiments need to vary. A job description you can diff is a job description
you can measure.

Copied rather than symlinked, and read-only material rather than the repository
itself: a loop that can write is a loop that could edit its own instructions.

**Where the desk lives is the employee's, not this module's.** The original
computed it from `__file__`, which was right while this code sat inside one
employee's package and is wrong from a shared one: `__file__` now resolves into
the library, so every employee would be handed the same desk — and the desk is
the whole of what distinguishes them. `Desk` carries the root instead.
"""

import os
import pathlib
import shutil
import sys
from dataclasses import dataclass

from core.config import Config

COMPANY_ENV = (
    "SHOP_API_URL",
    "SHOP_API_KEY",
    "SHOP_TIMEZONE",
    "MATOMO_URL",
    "MATOMO_SITE_ID",
    "MATOMO_AGENT_TOKEN",
    "LOKI_URL",
    "FEED_HOST",
    "FEED_PORT",
    "FEED_USER",
    "FEED_PASSWORD",
)
"""What the role is given to reach the company, named explicitly.

An allow-list rather than the whole environment. The employee's own machinery
lives in the same environment — the bus URL, the model settings — and a shell
command the model writes has no business reading them.
"""


@dataclass(frozen=True)
class Desk:
    """One employee's desk: where its material is, and what it may reach.

    Two fields, and they are the two halves of a role. `root` is what the
    employee is told — the brief and the skills, editable and diffable. Anything
    that the employee is *given* — the credentials — is named in `company_env`
    and read from the process environment, never stored here: a value on this
    object is a value that ends up in a repr, a log line or a record.
    """

    root: pathlib.Path
    """The directory holding `AGENTS.md`, `skills/` and the company CA."""
    company_env: tuple[str, ...] = COMPANY_ENV
    """Which variables reach the loop. Per-desk, because the next experiments
    vary access rather than the model: two employees holding different tuples is
    the boundary being measured."""


def brief(desk: Desk) -> str:
    """The entry point both harnesses read, from `<desk>/AGENTS.md`.

    A file rather than a string in this module, because it is the job
    description and the next experiments vary it. Something you edit, read and
    diff is something you can hold constant on purpose; a triple-quoted
    constant is not.

    It deliberately says how to work and never what to look for. Naming where to
    start would make every run a test of that hint, and the point is to measure
    whether the company can be understood, not whether a good hint helps.
    """
    return (desk.root / "AGENTS.md").read_text()


CA_FILE = "company-ca.crt"
"""The company's own certificate authority, referenced as `$COMPANY_CA`.

The systems answer on `.test` domains with certificates this CA signed, so
plain `curl` fails verification and an agent reads that as an unreachable
system. Trusting the company's CA is what a real employee's machine does;
`--insecure` is what somebody does at 2am and never removes.

A relative name: commands run with the workspace as their working directory.
"""


DATA = "data"
"""Where every response lands, created empty so the first fetch works.

The brief and every worked example write to `data/<name>`, and `curl -o` into a
directory that does not exist fails with "Failed to open the file" — an error
about the local filesystem, arriving in the middle of a call to a remote system,
which is exactly the kind of thing an investigation misreads as the system being
unreachable. Shipping the directory costs nothing and removes the ambiguity.

Empty, so git cannot carry it: made here rather than kept in the desk.
"""


def prepare(desk: Desk, workspace: pathlib.Path) -> None:
    """Lay `desk` out in `workspace`.

    **The furniture is copied into the evidence.** `workspace` sits inside the
    run's own directory, so everything written here — the skills tree, the API
    contract, the brief — is kept beside what the investigation actually
    produced. That is a live cost, not a historical one: the desk is identical
    on every run and lives in this repository, so a reader opening a run
    directory to see what an analyst did wades through several hundred KB of
    specification that was never in question.

    Left as it is deliberately, because the alternative is worse. A driver that
    laid the desk out somewhere else and copied only the new files back has to
    decide which files are new, and the last thing that tried it deleted a
    finished investigation by copying a directory onto itself. If this is ever
    changed, the thing to preserve is that a run keeps what cannot be
    reproduced — and the desk always can be.
    """
    skills = workspace / ".agents" / "skills"
    skills.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(desk.root / "skills", skills)
    (workspace / "AGENTS.md").write_text(brief(desk))
    shutil.copy2(desk.root / CA_FILE, workspace / CA_FILE)
    (workspace / DATA).mkdir()


MACHINERY = (
    "HOME",
    "TMPDIR",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "OPENAI_API_KEY",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)
"""What the CLI itself needs, as opposed to what the role is given.

Separate from `COMPANY_ENV` on purpose: these exist so `codex` and `opencode`
can start and authenticate, not so the investigation can reach anything. The
provider key is the uncomfortable one — it must pass for the loop to run at all,
and it is the single variable you would least like a shell command to read. It
is named here rather than inherited silently so that the exception is visible.
"""


def child_env(desk: Desk, config: Config) -> dict[str, str]:
    """The complete environment a harness process is given.

    Built rather than merged. Both drivers used `{**os.environ, **company_env()}`,
    which handed the child everything this process had: the bus URL, the
    namespace, the employee's own settings. Under codex that was contained
    afterwards by `shell_environment_policy.include_only`, so the boundary was the
    vendor's sandbox rather than ours. **opencode has no such setting**, so under
    it the allow-list was decoration: a shell command could read `REDIS_URL` and
    write onto the employee's own action stream, letting the investigated system
    drive the investigator.

    Constructing it here makes the two harnesses receive the same environment,
    which a campaign comparing loops requires — otherwise it is also comparing
    permissions.
    """
    given = {name: os.environ[name] for name in MACHINERY if os.environ.get(name)}
    given.update(company_env(desk, config))
    return given


def company_env(desk: Desk, config: Config) -> dict[str, str]:
    """The credentials and the interpreter, in the vocabulary the skills speak.

    **Taken from the resolved configuration, not from this process's
    environment.** The deployment names the shop's key once — `AGENT_API_KEY`,
    the same name every other employee reads it under — and the skills go on
    saying `$SHOP_API_KEY`, which is theirs. This function is where the two meet,
    and it is the only place that has to know they are the same thing.

    It used to copy the names straight out of `os.environ`, which meant the
    deployment had to spell them the skills' way. That is how philip and ethan
    came to read `SHOP_API_KEY` while the other five read `AGENT_API_KEY`: not a
    decision, a passthrough.

    Missing variables are left out rather than passed empty: a skill that says
    the token lives in `MATOMO_AGENT_TOKEN` should fail loudly when it does not,
    not send an empty string and read as a rejected credential.
    """
    supplied = {
        "SHOP_API_URL": config.shop.base_url,
        "SHOP_API_KEY": config.shop.api_key,
        "SHOP_TIMEZONE": config.shop.timezone,
        "MATOMO_URL": config.matomo.base_url,
        "MATOMO_SITE_ID": config.matomo.site_id,
        "MATOMO_AGENT_TOKEN": config.matomo.token,
        "LOKI_URL": config.loki.base_url,
        "FEED_HOST": config.feed.host,
        "FEED_PORT": str(config.feed.port),
        "FEED_USER": config.feed.user,
        "FEED_PASSWORD": config.feed.password,
    }
    # `desk.company_env` stays the allow-list: a desk that narrows it hands the
    # role less, and the test that pins that behaviour still means something.
    given = {
        name: supplied[name]
        for name in desk.company_env
        if supplied.get(name, "").strip()
    }
    given["PYTHON"] = str(interpreter())
    # `PATH`, because codex replaces it with its own inside the sandbox and
    # `curl` is not on that one. Watched live, an agent spent four commands per
    # investigation hunting for an absolute path: `command not found: curl`,
    # then `print -r -- "$PATH"`, then a loop over `/usr/bin/curl /bin/curl
    # /opt/homebrew/bin/curl`, then the real call. Every skill that uses curl
    # paid that toll, and no test could see it: the contract suite runs commands
    # in an ordinary shell, and the functional suite reads only the answer.
    given["PATH"] = os.environ.get("PATH", "")
    given["COMPANY_CA"] = CA_FILE
    return given


def interpreter() -> pathlib.Path:
    """The Python a skill's scripts must be run with.

    Not `python3`. The sandbox has the system interpreter, which has none of the
    employee's dependencies: the ERP skill ships a script that imports
    `paramiko`, and run under `python3` it fails with `ModuleNotFoundError` — an
    error an investigation reads as "the feed is unreachable" rather than "I used
    the wrong Python".

    Passed as `$PYTHON` so a skill names it explicitly instead of a script
    guessing.

    The running interpreter, where the original preferred a `.venv/bin/python`
    resolved from `__file__`. Inside one employee's package those named the same
    file; from a shared library `__file__` lands in site-packages and the venv
    beside it belongs to nobody. Whatever imported this module is by definition
    the interpreter holding the dependencies a skill's script needs.
    """
    return pathlib.Path(sys.executable)
