"""Optional FUSE view for token-gated protected files."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from typing import Any

from .core import _ensure_authorized, load_manifest

try:
    from fuse import FUSE, FuseOSError, LoggingMixIn, Operations
except ImportError:  # pragma: no cover - optional dependency
    FUSE = None
    FuseOSError = OSError

    class LoggingMixIn:  # type: ignore[no-redef]
        """Fallback placeholder when fusepy is unavailable."""

    class Operations:  # type: ignore[no-redef]
        """Fallback placeholder when fusepy is unavailable."""


class ProtectedFilesFuse(LoggingMixIn, Operations):  # pragma: no cover - exercised only when fuse is installed
    """Expose protected files from managed state storage through one directory."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def _manifest(self):
        return load_manifest(self.root_dir)

    def _entry(self, name: str):
        for config in self._manifest().files.values():
            if Path(config.path).name == name and config.mount_path:
                return config
        raise FuseOSError(errno.ENOENT)

    def _managed_path(self, name: str) -> Path:
        return Path(self._entry(name).managed_path)

    def _assert_write_auth(self, name: str) -> None:
        config = self._entry(name)
        try:
            _ensure_authorized(self.root_dir, config)
        except PermissionError as exc:
            raise FuseOSError(errno.EACCES) from exc

    def getattr(self, path: str, fh: int | None = None) -> dict[str, Any]:
        if path == "/":
            now = int(os.stat_result((0,) * 10).st_ctime or 0)
            return {
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
                "st_ctime": now,
                "st_mtime": now,
                "st_atime": now,
            }
        managed = self._managed_path(path.lstrip("/"))
        st = managed.stat()
        return {
            "st_atime": st.st_atime,
            "st_ctime": st.st_ctime,
            "st_gid": st.st_gid,
            "st_mode": stat.S_IFREG | 0o644,
            "st_mtime": st.st_mtime,
            "st_nlink": 1,
            "st_size": st.st_size,
            "st_uid": st.st_uid,
        }

    def readdir(self, path: str, fh: int):
        yield "."
        yield ".."
        for config in self._manifest().files.values():
            if config.mount_path:
                yield Path(config.path).name

    def open(self, path: str, flags: int) -> int:
        name = path.lstrip("/")
        writable = flags & (os.O_WRONLY | os.O_RDWR | os.O_TRUNC | os.O_APPEND)
        if writable:
            self._assert_write_auth(name)
        return os.open(self._managed_path(name), flags)

    def create(self, path: str, mode: int, fi=None) -> int:
        name = path.lstrip("/")
        self._assert_write_auth(name)
        return os.open(self._managed_path(name), os.O_WRONLY | os.O_CREAT, mode)

    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, size)

    def write(self, path: str, data: bytes, offset: int, fh: int) -> int:
        self._assert_write_auth(path.lstrip("/"))
        os.lseek(fh, offset, os.SEEK_SET)
        return os.write(fh, data)

    def truncate(self, path: str, length: int, fh: int | None = None) -> None:
        name = path.lstrip("/")
        self._assert_write_auth(name)
        with open(self._managed_path(name), "r+b") as handle:
            handle.truncate(length)

    def unlink(self, path: str) -> None:
        name = path.lstrip("/")
        self._assert_write_auth(name)
        self._managed_path(name).unlink()

    def rename(self, old: str, new: str) -> None:
        raise FuseOSError(errno.EPERM)

    def chmod(self, path: str, mode: int) -> int:
        return 0

    def chown(self, path: str, uid: int, gid: int) -> int:
        return 0

    def utimens(self, path: str, times=None) -> None:
        name = path.lstrip("/")
        os.utime(self._managed_path(name), times)


def mount_protected_files(root_dir: Path, mount_dir: Path, *, foreground: bool = True) -> dict[str, Any]:
    """Mount protected files via FUSE when the optional dependency exists."""
    if FUSE is None:
        from .core import _set_fuse_status

        _set_fuse_status(root_dir, "disabled")
        raise RuntimeError(
            "FUSE mode requires the optional 'fusepy' runtime dependency and libfuse on the host."
        )
    mount_dir.mkdir(parents=True, exist_ok=True)
    FUSE(ProtectedFilesFuse(root_dir), str(mount_dir), foreground=foreground, allow_other=False)
    return {"ok": True, "mount_dir": str(mount_dir)}
