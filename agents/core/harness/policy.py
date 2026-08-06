"""What an employee is allowed to do, decided once and stated for both loops.

Four rules, and they describe a **role** rather than a precaution:

**No web search.** Not a safety measure. The analyst investigates one company,
and an answer that came from the web is an answer about somebody else's company.
It also breaks the experiment: a run that can search is not reproducible, because
the web is not the same twice.

The network itself is **open**, because the company answers over HTTP and the
analyst is handed an OpenAPI contract instead of a bespoke toolkit. Neither
harness can allow one host and refuse another, so this is the honest position:
the native search tool is gone, and the rest is an instruction until a filtering
proxy makes it a boundary again.

**Never ask a human.** The analyst runs behind a bus call with a deadline. A loop
that stops to ask a question does not pause, it hangs until its ttl and reports
nothing. Whatever it cannot establish, it must say so in its answer.

**Files are readable and writable.** An investigation needs somewhere to put
what it gathers, and it works in a scratch directory of its own.

**No approval prompts.** Same reason as asking: there is nobody there.

Every capability each harness offers is listed below and assigned explicitly,
including the ones that are obviously fine. A default is a decision somebody
made for you, and this file is where that stops. When a harness grows a new
capability, the test that checks this list fails, which is the point.
"""

ALLOW = "allow"
DENY = "deny"

OPENCODE_PERMISSIONS: dict[str, str] = {
    # Reading and writing, which is the job.
    "read": ALLOW,
    "edit": ALLOW,
    "glob": ALLOW,
    "grep": ALLOW,
    "list": ALLOW,
    "bash": ALLOW,
    "lsp": ALLOW,
    # Its own scratchpad. Harmless, and useful for a long investigation.
    "todowrite": ALLOW,
    # Subagents. A role is one person: a loop that spawns helpers is no longer
    # the thing being measured.
    "task": DENY,
    # Outside its working directory. ALLOW, and the reason is uncomfortable:
    # denying it bought no protection and broke the investigation.
    #
    # opencode does not sandbox `bash` at all — this key gates its *file* tools
    # only — so a denial here stopped nothing a shell command could not do
    # anyway. What it did do was disarm bash intermittently: opencode stages
    # command output under `~/.local/share/opencode/tool-output/`, outside the
    # project, and the blanket deny matched it. In one measured run six of
    # fifteen commands were refused this way, including the two reads that
    # would have reached Matomo and the shop.
    #
    # So this was a control that protected nothing and silently removed a third
    # of the evidence. It is ALLOW until opencode gains a real sandbox; the
    # boundary this comment used to claim has to be built somewhere it can
    # actually hold — a separate user or a container — and until then the
    # honest thing is not to pretend a key does it.
    "external_directory": ALLOW,
    # Skills, which are how the analyst is told the shape of each system: where
    # the shop's OpenAPI contract is, that Matomo describes itself, that Loki
    # wants nanoseconds. They document the company, not the investigation. A
    # skill that said "when orders drop, check the carrier feed" would be method,
    # and method belongs in the ticket or the comparison is between instruction
    # sets rather than between loops.
    "skill": ALLOW,
    # The three that make this file worth having.
    "question": DENY,
    "webfetch": DENY,
    "websearch": DENY,
    # Permission to keep going round. Denied because a loop that cannot stop
    # spends a deadline rather than reporting what it has.
    "doom_loop": DENY,
}
"""Every key opencode's schema accepts, each assigned.

Values are `allow` or `deny`, never `ask`: `ask` means waiting for a human, and
there is no human on the other end of a bus call."""

OPENCODE_MCP_PERMISSIONS: dict[str, str] = {
    # The three built-ins that would take the employee outside its tools.
    "bash": DENY,
    "edit": DENY,
    "webfetch": DENY,
}
"""What an employee equipped with an MCP server may do, instead of the table above.

A different role, not a stricter version of the same one. That employee reaches
the company **only** through typed tools it was given; opencode's own shell, its
editor and its fetcher would be four more ways into a company the experiment
means to reach one way, and each of them would also be a way out of the toolset
being measured.

Three keys rather than fifteen, and that is a known gap rather than a decision:
everything unlisted — `websearch` among them — runs on opencode's own default,
which the desk table above denies for a reason this one has not yet stated. It is
left as it was because two campaigns have already been run and graded against
exactly these three, and widening it silently would make the next campaign's
numbers a comparison against a different employee.
"""

CODEX_SANDBOX = "workspace-write"
"""Read and write inside the working directory, and nothing outside it."""

CODEX_CONFIG: dict[str, str] = {
    # THE key for the web, and the one that first got this wrong.
    # `tools.web_search` is a legacy flag under `[features]`; the governing
    # setting is this one, and its default is "cached", which is a working web
    # search. Set to false via the legacy flag, codex still ran a search and
    # returned live results.
    "web_search": '"disabled"',
    # Never stop for a human. There is none behind a bus call.
    "approval_policy": '"never"',
    # And accept the work rather than queue it for a reviewer who will not come.
    "approvals_reviewer": '"auto_review"',
    # OPEN, because the company is reached over HTTP and the analyst is given an
    # OpenAPI contract rather than a hand-built toolkit. It has to be able to
    # call what the contract describes.
    #
    # The cost is stated plainly: neither harness offers per-host network
    # control, so a shell that can reach the shop can also reach the internet.
    # `web_search` above removes the native tool, but "no internet" is now an
    # instruction rather than a boundary. Making it a boundary again means a
    # local proxy that forwards only to the company's hosts.
    "sandbox_workspace_write.network_access": "true",
    # Writes stay in the working directory. Without these, $TMPDIR and /tmp are
    # writable and an investigation can leave things outside its own scratch.
    "sandbox_workspace_write.exclude_tmpdir_env_var": "true",
    "sandbox_workspace_write.exclude_slash_tmp": "true",
    # No login shell: it would source dotfiles and pull in an environment nobody
    # here chose.
    "allow_login_shell": "false",
    # The shell itself stays on. The analyst needs it to work with the files it
    # is allowed to read and write; the sandbox is what bounds it, not its
    # absence.
    "features.shell_tool": "true",
    # `core` alone forwards nothing custom: a run's shell saw 22 variables and
    # none of the company's, so every skill failed with KeyError while the
    # environment looked correct from outside. Proven by reading a persisted
    # trace, which is what persistence is for.
    "shell_environment_policy.inherit": '"all"',
    # So the filtering is done here instead, by name. `include_only` keeps the
    # values out of argv — passing them with `set` would put credentials in the
    # process table for anyone running `ps`.
    "shell_environment_policy.include_only": "[{names}]",
}
"""Passed as `-c key=value`, alongside `--strict-config`.

Values are TOML: strings are quoted here so codex parses them as strings rather
than falling back to a bare literal.

`include_only` carries a `{names}` placeholder, filled by `codex.build_argv`
from the desk's allow-list so the two cannot drift apart.

`--strict-config` matters as much as any single value. Without it an unknown key
is ignored in silence, and this file already proved how that ends: a setting
that looked right, read right, and did nothing."""
