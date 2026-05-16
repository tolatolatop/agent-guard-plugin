"""FUSE-backed file locks for sensitive workflow state files."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

DEFAULT_TOKEN_ENV = "AGENT_GUARD_LOCK_TOKEN"
LOCKS_DIR = ".agent/locks"
MANIFEST_PATH = f"{LOCKS_DIR}/manifest.json"
GRANTS_DIR = f"{LOCKS_DIR}/grants"
FUSE_MOUNT_DIR = f"{LOCKS_DIR}/mount"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _relative_key(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _safe_name(path: str) -> str:
    return _relative_key(path).replace("/", "__")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _write_json(file_path: Path, value: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _set_fuse_status(root_dir: Path, status: str) -> None:
    from agent_guard.state import update_state

    try:
        update_state(root_dir, lambda current: {**current, "fuse": status})
    except RuntimeError:
        return


def fuse_runtime_available() -> bool:
    """Return whether the optional FUSE runtime is importable."""
    from .fuse_fs import FUSE

    return FUSE is not None


@dataclass(frozen=True)
class FileLockConfig:
    path: str
    mode: str
    token_hash: str
    token_env: str
    managed_path: str
    mount_path: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "FileLockConfig":
        return cls(
            path=str(value["path"]),
            mode=str(value.get("mode") or "fuse"),
            token_hash=str(value["token_hash"]),
            token_env=str(value.get("token_env") or DEFAULT_TOKEN_ENV),
            managed_path=str(value["managed_path"]),
            mount_path=str(value["mount_path"]),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mode": self.mode,
            "token_hash": self.token_hash,
            "token_env": self.token_env,
            "managed_path": self.managed_path,
            "mount_path": self.mount_path,
        }


@dataclass(frozen=True)
class FileLockGrant:
    path: str
    token_hash: str
    expires_at: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "FileLockGrant":
        return cls(
            path=str(value["path"]),
            token_hash=str(value["token_hash"]),
            expires_at=str(value["expires_at"]),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "token_hash": self.token_hash,
            "expires_at": self.expires_at,
        }

    def is_active(self, now: datetime | None = None) -> bool:
        expires_at = _parse_timestamp(self.expires_at)
        if expires_at is None:
            return False
        return expires_at > (now or _utc_now())


@dataclass(frozen=True)
class FileLockManifest:
    files: dict[str, FileLockConfig]

    @classmethod
    def empty(cls) -> "FileLockManifest":
        return cls(files={})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "version": 1,
            "files": {
                key: config.to_mapping()
                for key, config in sorted(self.files.items())
            },
        }


def manifest_path(root_dir: Path) -> Path:
    return root_dir / MANIFEST_PATH


def load_manifest(root_dir: Path) -> FileLockManifest:
    file_path = manifest_path(root_dir)
    if not file_path.exists():
        return FileLockManifest.empty()
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    if not isinstance(files, dict):
        raise RuntimeError("file-lock manifest files must be a JSON object.")
    return FileLockManifest(
        files={_relative_key(key): FileLockConfig.from_mapping(value) for key, value in files.items()}
    )


def _save_manifest(root_dir: Path, manifest: FileLockManifest) -> FileLockManifest:
    _write_json(manifest_path(root_dir), manifest.to_mapping())
    return manifest


def _grant_path(root_dir: Path, target_path: str) -> Path:
    return root_dir / GRANTS_DIR / f"{_safe_name(target_path)}.json"


def _load_grant(root_dir: Path, target_path: str) -> FileLockGrant | None:
    file_path = _grant_path(root_dir, target_path)
    if not file_path.exists():
        return None
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    grant = FileLockGrant.from_mapping(payload)
    if grant.is_active():
        return grant
    file_path.unlink(missing_ok=True)
    return None


def _ensure_authorized(
    root_dir: Path,
    config: FileLockConfig,
    *,
    token: str | None = None,
    env: dict[str, str] | None = None,
) -> None:
    supplied = token.strip() if isinstance(token, str) else ""
    if supplied and _hash_token(supplied) == config.token_hash:
        return

    resolved_env = env if env is not None else os.environ
    for env_name in (config.token_env, DEFAULT_TOKEN_ENV):
        env_value = resolved_env.get(env_name)
        if isinstance(env_value, str) and env_value and _hash_token(env_value) == config.token_hash:
            return

    grant = _load_grant(root_dir, config.path)
    if grant and grant.token_hash == config.token_hash:
        return

    raise PermissionError(
        f"Write access to {config.path} is locked. Provide the matching token or set {config.token_env}."
    )


def resolve_protected_path(root_dir: Path, relative_path: str) -> Path:
    key = _relative_key(relative_path)
    config = load_manifest(root_dir).files.get(key)
    if config is None:
        return root_dir / key
    return Path(config.managed_path)


def read_protected_text(root_dir: Path, relative_path: str, *, encoding: str = "utf-8") -> str:
    return resolve_protected_path(root_dir, relative_path).read_text(encoding=encoding)


def write_protected_text(
    root_dir: Path,
    relative_path: str,
    content: str,
    *,
    encoding: str = "utf-8",
    token: str | None = None,
    env: dict[str, str] | None = None,
    enforce_lock: bool = True,
) -> Path:
    key = _relative_key(relative_path)
    manifest = load_manifest(root_dir)
    config = manifest.files.get(key)
    target = root_dir / key if config is None else Path(config.managed_path)
    if config is not None and enforce_lock:
        _ensure_authorized(root_dir, config, token=token, env=env)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=encoding)
    return target


def delete_protected_file(
    root_dir: Path,
    relative_path: str,
    *,
    token: str | None = None,
    env: dict[str, str] | None = None,
    enforce_lock: bool = True,
) -> None:
    key = _relative_key(relative_path)
    manifest = load_manifest(root_dir)
    config = manifest.files.get(key)
    target = root_dir / key if config is None else Path(config.managed_path)
    if config is not None and enforce_lock:
        _ensure_authorized(root_dir, config, token=token, env=env)
    target.unlink(missing_ok=True)


def _managed_storage_path(root_dir: Path, relative_path: str) -> Path:
    from agent_guard.state import current_managed_state_dir

    managed_dir = current_managed_state_dir(root_dir)
    return managed_dir / Path(relative_path).name


def ensure_parent_symlink(root_dir: Path, config: FileLockConfig) -> Path:
    public_path = root_dir / config.path
    mount_target = root_dir / config.mount_path
    public_path.parent.mkdir(parents=True, exist_ok=True)
    if public_path.is_symlink() or public_path.exists():
        if public_path.is_symlink() and public_path.resolve(strict=False) == mount_target.resolve(strict=False):
            return public_path
        if public_path.is_dir() and not public_path.is_symlink():
            raise RuntimeError(f"Cannot replace directory {public_path} with a file lock.")
        public_path.unlink()
    public_path.symlink_to(os.path.relpath(mount_target, start=public_path.parent))
    return public_path


def protect_file(
    root_dir: Path,
    relative_path: str,
    token: str,
    *,
    token_env: str = DEFAULT_TOKEN_ENV,
    mode: str = "fuse",
) -> dict[str, Any]:
    key = _relative_key(relative_path)
    if not token.strip():
        raise RuntimeError("file-lock token must be a non-empty string.")
    if mode != "fuse":
        raise RuntimeError("file-lock only supports fuse mode.")
    if not fuse_runtime_available():
        _set_fuse_status(root_dir, "disabled")
        raise RuntimeError("FUSE runtime is unavailable. file-lock only supports fuse mode.")

    manifest = load_manifest(root_dir)
    if key in manifest.files:
        raise RuntimeError(f"{key} is already protected by file-lock.")

    public_path = root_dir / key
    managed_path = _managed_storage_path(root_dir, key)
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    if public_path.exists() and not public_path.is_symlink():
        shutil.move(str(public_path), str(managed_path))
    elif not managed_path.exists():
        managed_path.write_text("", encoding="utf-8")

    config = FileLockConfig(
        path=key,
        mode="fuse",
        token_hash=_hash_token(token),
        token_env=token_env,
        managed_path=managed_path.as_posix(),
        mount_path=f"{FUSE_MOUNT_DIR}/{Path(key).name}",
    )
    updated = FileLockManifest(files={**manifest.files, key: config})
    _save_manifest(root_dir, updated)
    ensure_parent_symlink(root_dir, config)
    _set_fuse_status(root_dir, "enabled")
    return {
        "ok": True,
        "path": key,
        "mode": "fuse",
        "managed_path": config.managed_path,
        "mount_path": config.mount_path,
        "token_env": token_env,
        "public_path": public_path.as_posix(),
    }


def grant_file_lock(root_dir: Path, relative_path: str, token: str, ttl_seconds: int = 60) -> dict[str, Any]:
    key = _relative_key(relative_path)
    config = load_manifest(root_dir).files.get(key)
    if config is None:
        raise RuntimeError(f"{key} is not protected by file-lock.")
    if _hash_token(token) != config.token_hash:
        raise PermissionError(f"Provided token does not match lock for {key}.")
    expires_at = (_utc_now() + timedelta(seconds=max(ttl_seconds, 1))).isoformat()
    grant = FileLockGrant(path=key, token_hash=config.token_hash, expires_at=expires_at)
    _write_json(_grant_path(root_dir, key), grant.to_mapping())
    return {"ok": True, "path": key, "expires_at": expires_at}


def revoke_file_lock(root_dir: Path, relative_path: str) -> dict[str, Any]:
    key = _relative_key(relative_path)
    _grant_path(root_dir, key).unlink(missing_ok=True)
    return {"ok": True, "path": key}


def lock_status(root_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(root_dir)
    files: list[dict[str, Any]] = []
    for key, config in sorted(manifest.files.items()):
        grant = _load_grant(root_dir, key)
        files.append(
            {
                "path": key,
                "mode": config.mode,
                "token_env": config.token_env,
                "managed_path": config.managed_path,
                "mount_path": config.mount_path,
                "grant_active": bool(grant),
                "grant_expires_at": grant.expires_at if grant else None,
            }
        )
    return {"ok": True, "files": files}
