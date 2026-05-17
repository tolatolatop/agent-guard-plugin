"""Atomic filesystem writes for critical workflow state files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(target: Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Write text atomically by fsyncing a temp file and replacing the target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync so rename is durably recorded."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
