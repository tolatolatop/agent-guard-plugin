"""Helpers for the external Rust FUSE runtime."""
from __future__ import annotations

from pathlib import Path
import shutil


def runtime_binary() -> str | None:
    """Return the discovered external FUSE runtime binary, if any."""
    return shutil.which("agent-guard-fuse")


def mount_command(root_dir: Path) -> list[str]:
    """Return the explicit mount command for one workspace."""
    binary = runtime_binary()
    if binary is None:
        raise RuntimeError("agent-guard-fuse is not installed.")
    return [binary, "mount", "--root", str(root_dir.resolve())]


def unmount_command(root_dir: Path) -> list[str]:
    """Return the explicit unmount command for one workspace."""
    binary = runtime_binary()
    if binary is None:
        raise RuntimeError("agent-guard-fuse is not installed.")
    return [binary, "unmount", "--root", str(root_dir.resolve())]
