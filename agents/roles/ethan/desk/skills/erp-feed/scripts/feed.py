#!/usr/bin/env python3
"""List and read the ERP drop over SFTP.

Ships with the skill because nothing on this machine speaks SFTP: `sshpass` is
not installed and the system `curl` is built without SFTP support. A skill that
told you to use either would be documentation written from a manual rather than
from this environment, and an investigation following it reports that the
credentials are unavailable, which is true of nothing.

Run it with the interpreter in `$PYTHON`, never `python3`. `$PYTHON` has
paramiko; the system interpreter does not, and under it this file dies with
`ModuleNotFoundError`, which reads like an unreachable feed rather than the
wrong interpreter.

    "$PYTHON" feed.py ls [path]        size, UTC mtime and name, one per line
    "$PYTHON" feed.py cat <path>       whole file to stdout
    "$PYTHON" feed.py head <path> [n]  first n lines (default 20)

Paths are relative to the drop root. Credentials come from FEED_HOST,
FEED_PORT, FEED_USER and FEED_PASSWORD. Nothing here writes.
"""

from __future__ import annotations

import datetime as dt
import os
import stat as statmod
import sys

import paramiko

REQUIRED = ("FEED_HOST", "FEED_USER", "FEED_PASSWORD")
"""FEED_PORT is optional and defaults to 22; these are not."""

TIMEOUT_S = 15.0
"""Fail fast: a hung connection costs an investigation more than an error does."""

HEAD_LINES = 20


def connect() -> paramiko.SFTPClient:
    """Open an SFTP session from the credentials in the environment."""
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"not set in the environment: {', '.join(missing)}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=os.environ["FEED_HOST"],
        port=int(os.environ.get("FEED_PORT") or 22),
        username=os.environ["FEED_USER"],
        password=os.environ["FEED_PASSWORD"],
        # The drop takes a password. Offering keys or an agent would only spend
        # attempts and can trip a server's max-auth-tries before the password.
        look_for_keys=False,
        allow_agent=False,
        timeout=TIMEOUT_S,
        banner_timeout=TIMEOUT_S,
        auth_timeout=TIMEOUT_S,
    )
    return client.open_sftp()


def describe(attrs: paramiko.SFTPAttributes, name: str) -> str:
    """One row: kind, size in bytes, mtime as UTC, name.

    Not the server's own `longname`, whose format is server-dependent.
    """
    kind = "d" if statmod.S_ISDIR(attrs.st_mode or 0) else "-"
    when = "?" * 20
    if attrs.st_mtime is not None:
        moment = dt.datetime.fromtimestamp(attrs.st_mtime, dt.UTC)
        when = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{kind} {attrs.st_size or 0:>9} {when} {name}"


def do_ls(sftp: paramiko.SFTPClient, path: str) -> None:
    """Long listing of a directory, or a single row when `path` is a file."""
    attrs = sftp.stat(path)
    if not statmod.S_ISDIR(attrs.st_mode or 0):
        print(describe(attrs, path))
        return
    for entry in sorted(sftp.listdir_attr(path), key=lambda a: a.filename):
        print(describe(entry, entry.filename))


def do_cat(sftp: paramiko.SFTPClient, path: str) -> None:
    """Whole file to stdout. `utf-8-sig` drops a byte-order mark if one appears."""
    # "rb" throughout: paramiko's read() hands back bytes but readline() hands
    # back str unless the file was opened binary, and one decode is enough.
    with sftp.open(path, "rb") as handle:
        handle.prefetch()  # a round trip per chunk otherwise
        sys.stdout.write(handle.read().decode("utf-8-sig", "replace"))


def do_head(sftp: paramiko.SFTPClient, path: str, count: int) -> None:
    """First `count` lines, read line by line so a large feed is not pulled whole."""
    with sftp.open(path, "rb") as handle:
        for index, line in enumerate(handle):
            if index >= count:
                break
            sys.stdout.write(line.decode("utf-8-sig", "replace"))


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    args = argv[2:]
    if command not in ("ls", "cat", "head"):
        print(__doc__, file=sys.stderr)
        return 2
    if command != "ls" and not args:
        print(f"{command} needs a path", file=sys.stderr)
        return 2
    sftp = connect()
    try:
        if command == "ls":
            do_ls(sftp, args[0] if args else ".")
        elif command == "cat":
            do_cat(sftp, args[0])
        else:
            do_head(sftp, args[0], int(args[1]) if len(args) > 1 else HEAD_LINES)
    finally:
        sftp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
