"""Read-only access to the ERP file drop, with optional CSV table import."""

import csv
import io
from typing import Any

import paramiko

from core.config import FeedConfig
from roles.blair.tools import tables

MAX_BYTES = 12_000
MAX_PREVIEW = 3


def _connect(cfg: FeedConfig) -> tuple[paramiko.Transport, paramiko.SFTPClient]:
    transport = paramiko.Transport((cfg.host, cfg.port))
    transport.connect(username=cfg.user, password=cfg.password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    if sftp is None:  # pragma: no cover - allowed by Paramiko's annotations
        transport.close()
        raise RuntimeError("could not open SFTP session")
    return transport, sftp


def list_files(cfg: FeedConfig) -> list[dict[str, Any]] | dict[str, Any]:
    """Files currently published by the ERP, with sizes when available."""
    try:
        transport, sftp = _connect(cfg)
    except (OSError, paramiko.SSHException) as exc:
        return {"error": f"file service unavailable: {exc}"}
    try:
        found: list[dict[str, Any]] = []
        for name in sorted(sftp.listdir(cfg.directory)):
            try:
                size = sftp.stat(f"{cfg.directory}/{name}").st_size
            except OSError:
                size = None
            found.append({"file": name, "bytes": size})
        return found
    finally:
        sftp.close()
        transport.close()


def read_file(
    cfg: FeedConfig,
    name: str,
    *,
    offset: int = 0,
    save_as: str | None = None,
) -> dict[str, Any]:
    """Read a byte window, or import a complete CSV as a local table."""
    safe = name.strip().lstrip("/")
    if not safe or "/" in safe or safe.startswith("."):
        return {"file": name, "error": "only a direct filename is allowed"}
    try:
        raw = _download(cfg, safe)
    except (OSError, paramiko.SSHException) as exc:
        return {"file": safe, "error": f"file service unavailable: {exc}"}
    if save_as:
        if not safe.casefold().endswith(".csv"):
            return {"file": safe, "error": "save_as currently supports CSV files"}
        text = raw.decode("utf-8-sig", errors="replace")
        rows = [dict(row) for row in csv.DictReader(io.StringIO(text))]
        receipt = tables.save(
            save_as,
            rows,
            source=f"feed:{safe}",
            complete=True,
        )
        return {
            "file": safe,
            "bytes_total": len(raw),
            "preview": rows[:MAX_PREVIEW],
            "table": receipt,
        }

    offset = max(0, offset)
    chunk = raw[offset : offset + MAX_BYTES]
    read_to = offset + len(chunk)
    result: dict[str, Any] = {
        "file": safe,
        "bytes_total": len(raw),
        "offset": offset,
        "returned_bytes": len(chunk),
        "complete": read_to >= len(raw),
        "text": chunk.decode("utf-8", errors="replace"),
    }
    if not result["complete"]:
        result["next_offset"] = read_to
    return result


def _download(cfg: FeedConfig, name: str) -> bytes:
    transport, sftp = _connect(cfg)
    try:
        buffer = io.BytesIO()
        sftp.getfo(f"{cfg.directory}/{name}", buffer)
        return buffer.getvalue()
    finally:
        sftp.close()
        transport.close()
