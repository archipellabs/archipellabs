"""A cancelled investigation must not leave its loop running.

Exercised against real subprocesses rather than mocks, because the defect was
entirely about real process semantics: `CancelledError` is a `BaseException`,
so `except TimeoutError` never saw it, and the deadline that was supposed to
bound the run lived in the event loop that had just died. A mock would have
agreed with the broken code.

Cheap enough for the unit tier — it sleeps, it does not think.
"""

import asyncio
import os
import pathlib
import signal

import pytest

from core.harness.codex import CodexHarness
from core.harness.desk import Desk

DESK = Desk(root=pathlib.Path("desk"))
"""Required to build a driver and never read by the reaping path: what is under
test is what happens to a process, not what the employee was told."""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_cancelling_a_run_kills_the_loop_and_its_children() -> None:
    """The failure that cost 90 minutes of tokens, reproduced.

    `sh -c 'sleep 300 & wait'` stands in for codex: a parent with a child of its
    own. Signalling only the parent leaves the child, which is why the fix kills
    the process group.
    """
    harness = CodexHarness(desk=DESK, env={}, timeout_s=60.0)
    started: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def run() -> None:
        process = await asyncio.create_subprocess_exec(
            "/bin/sh", "-c", "sleep 300 & echo $!; wait",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        started.set_result(process.pid)
        try:
            await asyncio.wait_for(process.communicate(), timeout=60)
        finally:
            await harness._reap(process)

    task = asyncio.ensure_future(run())
    pid = await started
    await asyncio.sleep(0.2)
    assert alive(pid)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.3)
    assert not alive(pid), "the loop survived its own cancellation"


async def test_reaping_an_already_finished_process_is_a_no_op() -> None:
    """The ordinary case: nothing to signal, and no exception for trying."""
    process = await asyncio.create_subprocess_exec(
        "/bin/sh", "-c", "exit 0", start_new_session=True
    )
    await process.wait()

    await CodexHarness(desk=DESK, env={})._reap(process)

    assert process.returncode == 0


async def test_a_loop_that_ignores_TERM_is_killed_anyway() -> None:
    """TERM first so codex can close its children, KILL because it must end."""
    process = await asyncio.create_subprocess_exec(
        "/bin/sh", "-c", f"trap '' {int(signal.SIGTERM)}; sleep 300",
        start_new_session=True,
    )
    await asyncio.sleep(0.2)

    await asyncio.wait_for(CodexHarness(desk=DESK, env={})._reap(process), timeout=20)

    assert not alive(process.pid)
