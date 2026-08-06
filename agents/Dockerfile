# syntax=docker/dockerfile:1

# One image for every employee. Which one it is, is `AGENT_NAME` at run time.
#
# Seven images differing only in a name would be seven things to rebuild when
# the shared machinery changes, and the shared machinery is most of the code.
# The union of the seven dependency sets resolved to exactly the packages the
# seven already carried — 66 of them, none added — so there was nothing to save
# by splitting it either.
#
# Heavier than a Python service usually is, because two of the employees drive
# CLIs rather than libraries: philip and ethan spawn `codex` and `opencode`, and
# charlie and dana spawn `opencode` to host their MCP server. Those two binaries
# alone are 479MB and cannot be made smaller from here — the rest of this file
# is about not shipping anything else.

# --- the Python environment -------------------------------------------------
FROM python:3.14-slim AS deps

# uv, pinned by digest for reproducible builds (resolve a newer one with
# `docker pull ghcr.io/astral-sh/uv:latest`). It stays in this stage: it is a
# build tool, and at 55MB it is not a rounding error in the final image.
COPY --from=ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=python3.14 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- the two agent CLIs -----------------------------------------------------
FROM python:3.14-slim AS clis

# **Pinned to an exact version, and deliberately current.** A range would let two
# builds of the same commit ship different loops, which is the one thing a lab
# comparing loops cannot afford.
#
# These are ahead of what this repository has measured: every campaign in
# `research/reports/` ran on opencode 1.3.13, and the pin below is 1.18.14 —
# fifteen minor versions. That is a deliberate reset, not an upgrade in place:
# results from before it and after it are separate experiments, and the first
# campaign on this image is a new baseline rather than a comparison with the
# last one.
#
# The musl prune is worth 181MB: opencode ships a glibc *and* a musl binary for
# this architecture and loads exactly one — `ldd` on the glibc build resolves
# `libc.so.6`, so on a Debian base the musl copy is never executed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g --no-fund --no-audit \
        @openai/codex@0.146.1 \
        opencode-ai@1.18.14 \
    && rm -rf /usr/local/lib/node_modules/opencode-ai/node_modules/*-musl \
    && rm -rf /var/lib/apt/lists/*

# --- what actually ships ----------------------------------------------------
FROM python:3.14-slim

# `curl` and `jq` are not conveniences: the desks are written in them — 34 curl
# and 16 jq calls in the Matomo skill alone — and an agent without them reads
# "command not found" as a system being unreachable. `nodejs` because codex's
# entry point is a `.js`; `npm` is not here because nothing runs it.
#
# **No `git` and no `openssh-client`.** Both were shipped on the assumption that
# codex wanted a repository and the ERP feed wanted an SSH client. Neither is
# used: the driver passes `--skip-git-repo-check` precisely because the working
# directory is scratch, and the feed is reached through paramiko. Together with
# the perl that git drags in, that was ~50MB of image serving nothing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl jq nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /opt/venv /opt/venv
COPY --from=clis /usr/local/lib/node_modules /usr/local/lib/node_modules

# Recreated, not copied. `npm` leaves these as symlinks into `node_modules`, and
# `COPY --from` dereferences a symlink — copying the two of them shipped 180MB
# of binaries that were already in the line above, and made the multi-stage
# build *larger* than the single-stage one it replaced.
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s ../lib/node_modules/opencode-ai/bin/opencode.exe /usr/local/bin/opencode

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY core/ ./core/
COPY roles/ ./roles/

# An unprivileged user with a real home.
#
# Both CLIs write there and neither says so loudly: codex keeps its auth store
# under `$CODEX_HOME`, opencode stages every tool result under
# `~/.local/share/opencode/`. Run as root with no home and the first symptom is
# an investigation that produces no output.
RUN useradd --create-home --uid 10001 analyst \
    && mkdir -p /var/lib/agent/runs /var/lib/agent/workspaces \
         /var/lib/agent/datasets /var/lib/agent/logs \
    && chown -R analyst:analyst /var/lib/agent /app
USER analyst
ENV HOME=/home/analyst

# Where the record of each investigation lands. Without it `runs_dir()` is
# relative to the working directory, which means the image's layout decides
# where the evidence goes — and mixed evidence is exactly how one employee's
# records ended up in another's directory.
ENV AGENT_TRANSCRIPT_DIR=/var/lib/agent/runs

# The three scratch directories the typed toolsets use, for the same reason. Left
# unset they resolve beside the code — inside the image layer — so a rebuilt
# container silently loses the datasets and downloaded logs an investigation
# built, and writes them into the source tree on the way. Pointed at the volume,
# they persist and they stay out of `roles/`.
ENV AGENT_WORKSPACE_DIR=/var/lib/agent/workspaces \
    AGENT_DATA_DIR=/var/lib/agent/datasets \
    AGENT_LOG_DIR=/var/lib/agent/logs

# One employee, a comma-separated list, or `*` for all of them — so the
# deployment decides how many processes this is, not the image. One container
# each isolates a crash; one container for all seven costs a quarter of the
# memory. Nothing about an employee changes between them.
#
# No default: an image that picks for you is an image that will quietly serve
# the wrong one. `main` refuses an empty or unknown name and says who exists.
ENV AGENT_NAME=""

CMD ["python", "-m", "core.main"]
