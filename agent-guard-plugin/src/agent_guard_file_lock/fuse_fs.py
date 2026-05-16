"""Helpers for the external Rust FUSE runtime."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .core import LOCK_ROOT, derive_state_id


@dataclass(frozen=True)
class WorkspaceRuntime:
    """Resolved runtime paths for one workspace mount."""

    root_dir: Path

    @property
    def state_id(self) -> str:
        return derive_state_id(self.root_dir)

    @property
    def normalized_root(self) -> str:
        return str(self.root_dir.resolve())

    @property
    def mount_dir(self) -> Path:
        return self.root_dir / ".agent"

    @property
    def pid_file(self) -> Path:
        return LOCK_ROOT / "runtime" / f"{self.state_id}.json"


def _workspace_runtime(root_dir: Path) -> WorkspaceRuntime:
    return WorkspaceRuntime(root_dir=root_dir)


def runtime_binary() -> str | None:
    """Return the discovered external FUSE runtime binary, if any."""
    return shutil.which("agent-guard-fuse")


def mount_command(root_dir: Path) -> list[str]:
    """Return the explicit mount command for one workspace."""
    binary = runtime_binary()
    if binary is None:
        raise RuntimeError("agent-guard-fuse is not installed.")
    runtime = _workspace_runtime(root_dir)
    return [binary, "mount", "--root", runtime.normalized_root]


def unmount_command(root_dir: Path) -> list[str]:
    """Return the explicit unmount command for one workspace."""
    binary = runtime_binary()
    if binary is None:
        raise RuntimeError("agent-guard-fuse is not installed.")
    runtime = _workspace_runtime(root_dir)
    return [binary, "unmount", "--root", runtime.normalized_root]


def pid_file(root_dir: Path) -> Path:
    """Return the pid metadata path for one workspace runtime."""
    return _workspace_runtime(root_dir).pid_file


def _read_pid_record(root_dir: Path) -> dict[str, int | str] | None:
    runtime = _workspace_runtime(root_dir)
    record_path = runtime.pid_file
    if not record_path.exists():
        return None
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("FUSE pid record must be a JSON object.")
    pid = payload.get("pid")
    root = payload.get("root")
    if not isinstance(pid, int) or not isinstance(root, str):
        raise RuntimeError("FUSE pid record must include integer pid and string root.")
    return {"pid": pid, "root": root}


def _write_pid_record(root_dir: Path, pid: int) -> None:
    runtime = _workspace_runtime(root_dir)
    record_path = runtime.pid_file
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps({"pid": pid, "root": runtime.normalized_root}, indent=2) + "\n",
        encoding="utf-8",
    )


def _remove_pid_record(root_dir: Path) -> None:
    pid_file(root_dir).unlink(missing_ok=True)


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_mount(root_dir: Path, timeout_seconds: float = 5.0) -> bool:
    runtime = _workspace_runtime(root_dir)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if runtime.mount_dir.exists() and runtime.mount_dir.is_mount():
            return True
        time.sleep(0.05)
    return False


def fuse_status(root_dir: Path) -> dict[str, object]:
    """Return current pid record and liveness for one workspace."""
    runtime = _workspace_runtime(root_dir)
    record = _read_pid_record(root_dir)
    if record is None:
        return {"running": False, "pid": None, "root": runtime.normalized_root}
    alive = _process_alive(int(record["pid"]))
    if not alive:
        _remove_pid_record(root_dir)
        return {"running": False, "pid": None, "root": runtime.normalized_root}
    return {"running": True, "pid": int(record["pid"]), "root": str(record["root"])}


def start_fuse(root_dir: Path, timeout_seconds: float = 5.0) -> int:
    """Start a detached FUSE runtime for one workspace and return its pid."""
    status = fuse_status(root_dir)
    if status["running"]:
        raise RuntimeError(
            f"agent-guard-fuse is already running for {root_dir.resolve()} "
            f"with pid {status['pid']}."
        )
    process = subprocess.Popen(
        mount_command(root_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    _write_pid_record(root_dir, process.pid)
    if not _wait_for_mount(root_dir, timeout_seconds=timeout_seconds):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        _remove_pid_record(root_dir)
        raise RuntimeError(f"agent-guard-fuse did not mount {root_dir.resolve()} in time.")
    return process.pid


def stop_fuse(root_dir: Path, timeout_seconds: float = 5.0) -> bool:
    """Unmount and stop the detached FUSE runtime for one workspace."""
    status = fuse_status(root_dir)
    if not status["running"]:
        return False
    subprocess.run(unmount_command(root_dir), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = int(status["pid"])
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _process_alive(pid):
            _remove_pid_record(root_dir)
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid_record(root_dir)
        return True
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if not _process_alive(pid):
            _remove_pid_record(root_dir)
            return True
        time.sleep(0.05)
    raise RuntimeError(f"agent-guard-fuse pid {pid} did not exit after unmount.")
