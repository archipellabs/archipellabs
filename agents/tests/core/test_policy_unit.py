"""The role, asserted rather than assumed.

The point of `policy` is that nothing is left to a default. These tests are what
make that true over time: a harness that grows a capability, or renames one,
fails here instead of quietly granting it.

`KNOWN_OPENCODE` is transcribed from opencode's published schema. When it drifts
this file is where you find out, which is the cheapest place to find out.
"""

import pathlib

from core.harness.codex import build_argv
from core.harness.desk import COMPANY_ENV, Desk
from core.harness.opencode_cli import server_config
from core.harness.policy import (
    ALLOW,
    CODEX_CONFIG,
    CODEX_SANDBOX,
    DENY,
    OPENCODE_MCP_PERMISSIONS,
    OPENCODE_PERMISSIONS,
)

KNOWN_OPENCODE = {
    "read", "edit", "glob", "grep", "list", "bash", "task",
    "external_directory", "lsp", "skill", "todowrite", "question",
    "webfetch", "websearch", "doom_loop",
}
"""Every permission opencode's schema accepts, as published."""

DESK = Desk(root=pathlib.Path("desk"))
"""Stands in for an employee's own. `build_argv` reads only its allow-list, so
nothing here has to exist on disk."""


def argv(desk: Desk = DESK) -> list[str]:
    """The command one investigation would run, with the paths that do not
    matter to this file filled in."""
    return build_argv(
        desk, pathlib.Path("s.json"), pathlib.Path("a.json"), "", "why?"
    )


def include_only(command: list[str]) -> str:
    """The one templated setting, as codex will receive it."""
    return next(x for x in command if "include_only" in x)


def test_every_opencode_capability_is_decided() -> None:
    """No default gets to decide anything. A capability missing here is one
    running on whatever opencode thinks is reasonable."""
    assert set(OPENCODE_PERMISSIONS) == KNOWN_OPENCODE


def test_nothing_is_left_to_ask() -> None:
    """`ask` means waiting for a human, and there is none behind a bus call: the
    loop would hang until its deadline and report nothing."""
    assert set(OPENCODE_PERMISSIONS.values()) <= {ALLOW, DENY}


def test_the_web_is_closed_on_both_harnesses() -> None:
    """An answer from the web is an answer about somebody else's company, and a
    run that can search is not reproducible."""
    assert OPENCODE_PERMISSIONS["webfetch"] == DENY
    assert OPENCODE_PERMISSIONS["websearch"] == DENY
    # The governing key, not the legacy `tools.web_search` flag. That one is
    # accepted, reads correctly, and leaves a working cached search running.
    assert CODEX_CONFIG["web_search"] == '"disabled"'
    assert "tools.web_search" not in CODEX_CONFIG
    # The network is deliberately open: the company answers over HTTP. So this
    # is a one-barrier policy, and the barrier is the missing native tool.
    assert CODEX_CONFIG["sandbox_workspace_write.network_access"] == "true"


def test_neither_harness_may_stop_to_ask() -> None:
    assert OPENCODE_PERMISSIONS["question"] == DENY
    assert CODEX_CONFIG["approval_policy"] == '"never"'
    assert CODEX_CONFIG["approvals_reviewer"] == '"auto_review"'


def test_writes_stay_inside_the_working_directory() -> None:
    """Otherwise an investigation leaves things in $TMPDIR and /tmp, outside the
    scratch directory that was supposed to contain it."""
    assert CODEX_CONFIG["sandbox_workspace_write.exclude_tmpdir_env_var"] == "true"
    assert CODEX_CONFIG["sandbox_workspace_write.exclude_slash_tmp"] == "true"


def test_the_shell_gets_the_company_and_nothing_else() -> None:
    """Two failure modes, one setting between them.

    `inherit = "core"` forwarded nothing custom: a run's shell saw 22 variables,
    none of them the company's, and every skill died on a KeyError while the
    environment looked right from outside. `inherit = "all"` would hand the
    employee's own machinery to every command the model writes. So: inherit
    everything, then filter by name.
    """
    assert CODEX_CONFIG["shell_environment_policy.inherit"] == '"all"'
    assert "include_only" in " ".join(CODEX_CONFIG)
    assert CODEX_CONFIG["allow_login_shell"] == "false"


def test_the_allow_list_is_the_desk_s() -> None:
    """One list, so a credential added to the desk reaches the shell without a
    second edit somewhere else."""
    rendered = include_only(argv())

    for name in COMPANY_ENV:
        assert f'"{name}"' in rendered
    assert '"PYTHON"' in rendered


def test_a_desk_that_reaches_less_sends_less() -> None:
    """The allow-list is per-desk because the next experiments vary access
    rather than the model: two employees holding different tuples is the
    boundary being measured, and it only exists if this is what codex is told."""
    narrow = Desk(root=pathlib.Path("desk"), company_env=("SHOP_API_URL",))

    rendered = include_only(argv(narrow))

    assert '"SHOP_API_URL"' in rendered
    assert '"MATOMO_AGENT_TOKEN"' not in rendered


def test_files_are_readable_and_writable() -> None:
    """The investigation needs somewhere to put what it gathers."""
    assert OPENCODE_PERMISSIONS["read"] == ALLOW
    assert OPENCODE_PERMISSIONS["edit"] == ALLOW
    assert CODEX_SANDBOX == "workspace-write"


def test_opencode_is_started_with_the_policy() -> None:
    """Stated in `policy` and never sent is the failure this catches."""
    assert server_config()["permission"] == OPENCODE_PERMISSIONS


def test_an_employee_with_tools_keeps_opencode_s_own_built_ins_shut() -> None:
    """A different role rather than a stricter version of the same one: it
    reaches the company only through the tools it was given, and opencode's
    shell, editor and fetcher are each a way out of the toolset being measured.

    Asserted key by key, and deliberately not against `KNOWN_OPENCODE`. The rest
    of that table runs on opencode's defaults here — `websearch` among them,
    which the desk role denies — and closing that gap changes what two graded
    campaigns were run against, so it is a decision to take rather than a test
    to widen.
    """
    assert OPENCODE_MCP_PERMISSIONS == {"bash": DENY, "edit": DENY, "webfetch": DENY}
    assert set(OPENCODE_MCP_PERMISSIONS) < KNOWN_OPENCODE


def test_codex_refuses_unknown_settings() -> None:
    """`--strict-config` is the difference between a policy that stopped
    applying and a run that says so. Without it, a key codex renames is dropped
    in silence."""
    command = argv()

    assert "--strict-config" in command
    for key, value in CODEX_CONFIG.items():
        # The allow-list is templated from the desk, so it is checked by
        # `test_the_allow_list_is_the_desk_s` rather than compared literally.
        if "{names}" in value:
            assert any(x.startswith(f"{key}=") for x in command)
            continue
        assert f"{key}={value}" in command
