"""The tool servers must be *runnable*, not merely spelled the way a test expects.

Written after a rename left `charlie` and `dana` pointing at
`employees.charlie.mcp_server`, a module that no longer existed. Every unit test
passed: the assertion compared the command to a literal, and the script that
rewrote the code rewrote the literal beside it. The two agreed, and were wrong
together.

The failure cost 601 seconds and zero tool calls per run — opencode waited for a
server that never started, and the harness timed out with nothing to show. From
the outside it read as an agent that had nothing to say.

So this asks the operating system instead of the source: import the module the
command names. It cannot be satisfied by editing a string.
"""

import importlib.util

import pytest

from core.main import employed


def mcp_modules() -> list[tuple[str, str]]:
    """Every employee that declares a tool server, and the module it names."""
    found = []
    for name in employed():
        module = __import__(f"roles.{name}.identity", fromlist=["MCP"])
        mcp = getattr(module, "MCP", None)
        if mcp is None:
            continue
        # ["<python>", "-m", "<module>"] — the module is what has to exist.
        assert "-m" in mcp.command, f"{name}'s server is not launched with -m"
        found.append((name, mcp.command[mcp.command.index("-m") + 1]))
    return found


@pytest.mark.parametrize(("employee", "module"), mcp_modules())
def test_the_declared_tool_server_is_a_module_that_exists(
    employee: str, module: str
) -> None:
    """Resolved through the import system, so a name that has moved fails here
    rather than as a timeout inside opencode twenty minutes later."""
    assert importlib.util.find_spec(module) is not None, (
        f"{employee} tells opencode to run `python -m {module}`, which does not "
        "resolve. opencode will wait for a server that never starts."
    )


def test_at_least_one_employee_declares_a_tool_server() -> None:
    """Otherwise the parametrisation above is empty and this file proves
    nothing while appearing to pass."""
    assert mcp_modules(), "no employee declares an MCP server — has MCP moved?"
