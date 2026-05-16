"""FUSE-backed file-lock library for agent-guard."""

from .core import (
    DEFAULT_TOKEN_ENV,
    FileLockConfig,
    FileLockGrant,
    FileLockManifest,
    delete_protected_file,
    ensure_parent_symlink,
    fuse_runtime_available,
    grant_file_lock,
    load_manifest,
    lock_status,
    protect_file,
    read_protected_text,
    resolve_protected_path,
    revoke_file_lock,
    write_protected_text,
)

__all__ = [
    "DEFAULT_TOKEN_ENV",
    "FileLockConfig",
    "FileLockGrant",
    "FileLockManifest",
    "delete_protected_file",
    "ensure_parent_symlink",
    "fuse_runtime_available",
    "grant_file_lock",
    "load_manifest",
    "lock_status",
    "protect_file",
    "read_protected_text",
    "resolve_protected_path",
    "revoke_file_lock",
    "write_protected_text",
]
