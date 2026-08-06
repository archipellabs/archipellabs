"""The ERP's file drop, over SFTP.

The company's master data as an employee reaches it: connect, list, open. There
is no history here and no repository access — the feed is read AS IT IS NOW, so
"Canada is missing from carriers.csv" has to be noticed rather than read off a
diff.
"""

import io
from typing import Any

import paramiko

from core.config import FeedConfig

MAX_FILE_BYTES = 20_000
"""A file window small enough to inspect without dominating every later turn."""


def _connect(cfg: FeedConfig) -> tuple[paramiko.Transport, paramiko.SFTPClient]:
    transport = paramiko.Transport((cfg.host, cfg.port))
    transport.connect(username=cfg.user, password=cfg.password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    if sftp is None:  # pragma: no cover - paramiko types allow None
        transport.close()
        raise RuntimeError("could not open an SFTP session")
    return transport, sftp


def list_files(cfg: FeedConfig) -> list[str]:
    """The master-data files the ERP publishes."""
    transport, sftp = _connect(cfg)
    try:
        return sorted(sftp.listdir(cfg.directory))
    finally:
        sftp.close()
        transport.close()


def read_file(
    cfg: FeedConfig, name: str, max_bytes: int = MAX_FILE_BYTES, offset: int = 0
) -> dict[str, Any]:
    """One master-data file, or a window of it, and how much was left behind.

    It used to return a bare string cut at 20 KB with nothing to mark the cut.
    For a file that lists which markets the company ships to, that is the worst
    possible failure: a row past the boundary reads as a row that does not
    exist, and the tool would manufacture exactly the kind of incident it is
    being used to investigate. It now reports `complete` and `next_offset` like
    every other bounded answer here.
    """
    safe = name.strip().lstrip("/")
    if "/" in safe or safe.startswith(".."):
        raise ValueError("only files directly inside the feed directory can be read")

    transport, sftp = _connect(cfg)
    try:
        path = f"{cfg.directory}/{safe}"
        size = sftp.stat(path).st_size
        buffer = io.BytesIO()
        sftp.getfo(path, buffer)
        raw = buffer.getvalue()[offset : offset + max_bytes]
        read_to = offset + len(raw)
        result: dict[str, Any] = {
            "file": safe,
            "bytes_total": size,
            "offset": offset,
            "returned_bytes": len(raw),
            "complete": read_to >= (size or 0),
            "text": raw.decode("utf-8", errors="replace"),
        }
        if not result["complete"]:
            result["next_offset"] = read_to
        return result
    finally:
        sftp.close()
        transport.close()
