"""Minimal file-lock SDK for agent-guard and the external FUSE runtime."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
from typing import Any, Iterator

from agent_guard.atomic_io import atomic_write_text

LOCK_ROOT = Path.home() / ".agent-guard-fuse"
LOCK_FILE = LOCK_ROOT / "lock.json"
AGENT_DIR = ".agent"
DEFAULT_STATE_RELATIVE = ".agent/state.json"
DEFAULT_PLAN_RELATIVE = ".agent/plan.yaml"


def derive_state_id(root_dir: Path) -> str:
    """Return the stable state/workspace id derived from the workspace path."""
    return sha256(str(root_dir.resolve()).encode("utf-8")).hexdigest()[:32]


def fuse_runtime_available() -> bool:
    """Return whether the external FUSE runtime binary is discoverable."""
    return shutil.which("agent-guard-fuse") is not None


def lock_file_path() -> Path:
    """Return the global FUSE lock file path."""
    return LOCK_FILE


def normalize_root_path(root_dir: str | Path) -> str:
    """Return a normalized absolute workspace root path."""
    return str(Path(root_dir).resolve(strict=False))


def public_file_path(root_dir: Path, relative_path: str) -> Path:
    """Return an absolute public workspace path."""
    return root_dir / relative_path


def managed_root_path(root_dir: str | Path) -> Path:
    """Return the managed root for one workspace."""
    return LOCK_ROOT / "managed" / derive_state_id(Path(root_dir))


def managed_file_path(root_dir: Path, relative_path: str) -> Path:
    """Return the managed path for one .agent-relative file."""
    relative = Path(relative_path)
    parts = list(relative.parts)
    if parts and parts[0] == AGENT_DIR:
        relative = Path(*parts[1:]) if len(parts) > 1 else Path()
    return managed_root_path(root_dir) / relative


def fuse_enabled(root_dir: Path) -> bool:
    """Return whether the workspace appears to be mounted by the external FUSE runtime."""
    mount_dir = root_dir / AGENT_DIR
    return mount_dir.exists() and mount_dir.is_mount()


def load_locks() -> dict[str, Any]:
    """Load the global lock file."""
    if not LOCK_FILE.exists():
        return {"version": 3, "roots": {}}
    payload = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    roots = payload.get("roots", {})
    if not isinstance(roots, dict):
        raise RuntimeError("lock.json roots must be a JSON object.")
    normalized_roots: dict[str, dict[str, Any]] = {}
    for root, entry in roots.items():
        if not isinstance(entry, dict):
            raise RuntimeError("lock.json roots entries must be JSON objects.")
        files = entry.get("files", [])
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise RuntimeError("lock.json roots[*].files must be a JSON array of strings.")
        normalized_roots[str(root)] = {
            "managed": str(entry.get("managed") or ""),
            "token": str(entry.get("token") or ""),
            "files": [str(item) for item in files],
        }
    return {"version": int(payload.get("version", 3) or 3), "roots": normalized_roots}


def save_locks(payload: dict[str, Any]) -> None:
    """Persist the global lock file."""
    LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(LOCK_FILE, json.dumps(payload, indent=2) + "\n")


def _managed_root_for(root_dir: str | Path) -> str:
    return str(managed_root_path(root_dir).resolve(strict=False))


def lock(root_dir: str | Path) -> str:
    """Create or reuse the workspace token for one root path and return it."""
    normalized = normalize_root_path(root_dir)
    payload = load_locks()
    roots = dict(payload["roots"])
    entry = dict(roots.get(normalized, {}))
    token = entry.get("token") or secrets.token_hex(16)
    entry["managed"] = entry.get("managed") or _managed_root_for(normalized)
    entry["token"] = token
    entry["files"] = list(entry.get("files") or [])
    roots[normalized] = entry
    save_locks({"version": 3, "roots": roots})
    return token


def unlock(root_dir: str | Path, token: str) -> bool:
    """Release a workspace token and clear all locked files when the token matches."""
    normalized = normalize_root_path(root_dir)
    payload = load_locks()
    roots = dict(payload["roots"])
    entry = dict(roots.get(normalized, {}))
    if entry.get("token") != token:
        return False
    entry["managed"] = entry.get("managed") or _managed_root_for(normalized)
    entry["token"] = ""
    entry["files"] = []
    roots[normalized] = entry
    save_locks({"version": 3, "roots": roots})
    return True


def release_token(root_dir: str | Path, token: str) -> bool:
    """Release a workspace token while preserving the current locked-file set."""
    normalized = normalize_root_path(root_dir)
    payload = load_locks()
    roots = dict(payload["roots"])
    entry = dict(roots.get(normalized, {}))
    if entry.get("token") != token:
        return False
    entry["managed"] = entry.get("managed") or _managed_root_for(normalized)
    entry["token"] = ""
    entry["files"] = list(entry.get("files") or [])
    roots[normalized] = entry
    save_locks({"version": 3, "roots": roots})
    return True


def set_locked_files(root_dir: str | Path, files: list[str]) -> list[str]:
    """Persist the policy-managed locked-file set for one workspace."""
    normalized = normalize_root_path(root_dir)
    payload = load_locks()
    roots = dict(payload["roots"])
    entry = dict(roots.get(normalized, {}))
    normalized_files = sorted({str(item) for item in files})
    entry["managed"] = entry.get("managed") or _managed_root_for(normalized)
    entry["token"] = str(entry.get("token") or "")
    entry["files"] = normalized_files
    roots[normalized] = entry
    save_locks({"version": 3, "roots": roots})
    return normalized_files


def _file_context(file_path: str | Path) -> tuple[str, str]:
    path = Path(os.path.abspath(os.fspath(file_path)))
    if path.parent.name != AGENT_DIR:
        raise RuntimeError(f"{path} is not a supported .agent file path.")
    return normalize_root_path(path.parent.parent), path.name


def _validate_root_token(root_dir: str, token: str) -> dict[str, Any]:
    entry = dict(load_locks()["roots"].get(root_dir, {}))
    if entry.get("token") != token:
        raise PermissionError(f"{root_dir} is not locked by the provided token.")
    entry["managed"] = entry.get("managed") or _managed_root_for(root_dir)
    entry["files"] = list(entry.get("files") or [])
    return entry


def lock_file(file_path: str | Path, token: str) -> bool:
    """Mark one .agent file as locked for direct writes/deletes."""
    root_dir, file_name = _file_context(file_path)
    entry = _validate_root_token(root_dir, token)
    files = list(entry["files"])
    if file_name not in files:
        files.append(file_name)
    entry["files"] = files
    payload = load_locks()
    roots = dict(payload["roots"])
    roots[root_dir] = entry
    save_locks({"version": 3, "roots": roots})
    return True


def unlock_file(file_path: str | Path, token: str) -> bool:
    """Unmark one .agent file from the locked set."""
    root_dir, file_name = _file_context(file_path)
    entry = _validate_root_token(root_dir, token)
    entry["files"] = [name for name in entry["files"] if name != file_name]
    payload = load_locks()
    roots = dict(payload["roots"])
    roots[root_dir] = entry
    save_locks({"version": 3, "roots": roots})
    return True


def _validate_file_token(file_path: str | Path, token: str) -> tuple[str, str]:
    root_dir, file_name = _file_context(file_path)
    entry = _validate_root_token(root_dir, token)
    if file_name not in entry["files"]:
        raise PermissionError(f"{file_name} is not currently locked for {root_dir}.")
    return root_dir, file_name


@contextmanager
def _temporarily_unlock_file(file_path: str | Path, token: str) -> Iterator[None]:
    root_dir, file_name = _validate_file_token(file_path, token)
    payload = load_locks()
    roots = dict(payload["roots"])
    entry = dict(roots[root_dir])
    originally_locked = file_name in list(entry.get("files", []))
    entry["files"] = [name for name in entry.get("files", []) if name != file_name]
    roots[root_dir] = entry
    save_locks({"version": 3, "roots": roots})
    try:
        yield
    finally:
        payload = load_locks()
        roots = dict(payload["roots"])
        current = dict(roots.get(root_dir, {}))
        current["managed"] = current.get("managed") or _managed_root_for(root_dir)
        current["token"] = current.get("token") or token
        files = list(current.get("files") or [])
        if originally_locked and current.get("token") == token and file_name not in files:
            files.append(file_name)
        current["files"] = files
        roots[root_dir] = current
        save_locks({"version": 3, "roots": roots})


def write(file_path: str, data: str | bytes, token: str) -> bool:
    """Write through the public path while holding the matching file lock."""
    with _temporarily_unlock_file(file_path, token):
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            atomic_write_text(target, data)
    return True


def delete(file_path: str, token: str) -> bool:
    """Delete a public file while holding the matching file lock."""
    with _temporarily_unlock_file(file_path, token):
        Path(file_path).unlink(missing_ok=True)
    return True
