"""One process, whichever employee `AGENT_NAME` names.

    AGENT_NAME=philip python -m core.main

This replaced seven `src/app.py` files that were byte-identical apart from a
name in a docstring. It exists because the seven employees now share one
environment and one image, and an image that hard-codes who it is would be seven
images wearing one Dockerfile.

**The employee is still its own process.** The analyst is a simulated *employee*
and the simulator is the instrument; they share Redis so a ticket can be `call`ed
across, and nothing else — in particular not the simulator's database, which
records what each customer intended and would be an answer key.

What is no longer its own is the *directory*. Each employee used to read its own
`.env`, on the stated grounds that two employees reading one file cannot hold
different permissions. That boundary now lives where it always actually lived —
in the `Identity`, which decides the toolbox or the desk — and in the deployment,
which gives each container its own environment. One file per employee only ever
enforced it by convention.
"""

import importlib
import os
import pathlib

import roles
from core.harness.base import Identity
from core.service import app_for


def employed() -> list[str]:
    """Every employee the package holds, discovered rather than listed.

    Same rule as the lab's own `EMPLOYEES`: hiring someone is adding a directory
    and nothing else — and the test is the file that makes it an employee, not
    merely that the directory exists.

    Found by walking the tree rather than with `pkgutil.iter_modules`, which
    reports nothing here: these are PEP 420 namespace packages, carrying no
    `__init__.py` by the repository's own convention, and `iter_modules` only
    sees regular packages. It returned an empty list and the process refused
    every name it was given, which reads as "philip is not an employee".
    """
    return sorted(
        path.name
        for root in roles.__path__
        for path in pathlib.Path(root).iterdir()
        if path.is_dir()
        and not path.name.startswith((".", "_"))
        and (path / "identity.py").is_file()
    )


def identity(name: str) -> Identity:
    """The named employee's `IDENTITY`, or a refusal that says who exists.

    A name that is merely absent would otherwise start nothing and log nothing,
    and a container that exits silently reads exactly like one that is working.
    """
    if name not in employed():
        raise SystemExit(
            f"AGENT_NAME={name!r} is not an employee. Employed: {', '.join(employed())}."
        )
    module = importlib.import_module(f"roles.{name}.identity")
    found: Identity = module.IDENTITY
    if found.name != name:
        raise SystemExit(
            f"roles.{name} calls itself {found.name!r}. The directory is the "
            "name a caller routes on, so the two cannot disagree."
        )
    return found


def named(setting: str) -> list[str]:
    """The employees `AGENT_NAME` asks for.

    One name, several separated by commas, or `*` for everyone. The list exists
    so the *deployment* decides how many processes this is: one container per
    employee isolates a crash, one container for all seven costs a quarter of
    the memory. The image is the same either way, and so is the bus — each
    employee still answers on `<agent>.investigate` with one slot of its own.

    Duplicates are dropped rather than mounted twice: two services of one name
    would take turns on the same stream, so a ticket would reach whichever
    pulled first and the employee would appear to answer half its questions.
    Order is kept, because the first one named decides which configuration the
    queue is read from.
    """
    wanted = [part.strip() for part in setting.split(",") if part.strip()]
    if wanted == ["*"]:
        return employed()
    seen: dict[str, None] = {}
    for name in wanted:
        seen[name] = None
    return list(seen)


def main() -> None:
    setting = os.getenv("AGENT_NAME", "")
    if not setting:
        raise SystemExit(
            "set AGENT_NAME to an employee, a comma-separated list, or '*' for "
            f"all of them: {', '.join(employed())}."
        )
    mounted = [identity(name) for name in named(setting)]
    if not mounted:
        raise SystemExit(f"AGENT_NAME={setting!r} names nobody.")
    # `start()` is blocking and opens the loop itself, so nothing here wraps it
    # in `asyncio.run`.
    app_for(*mounted, level=os.getenv("LOG_LEVEL", "INFO")).start()


if __name__ == "__main__":
    main()
