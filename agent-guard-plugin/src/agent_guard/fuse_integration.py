"""Integration helpers for agent-guard-fuse managed protection."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_guard_file_lock import (
    fuse_enabled,
    fuse_runtime_available,
    fuse_status,
    managed_root_path,
    start_fuse,
    stop_fuse,
)


def _sync_workspace_protection(root_dir: Path) -> None:
    """Refresh long-lived managed document protection for the mounted workspace."""
    from .managed_documents import sync_managed_document_protection
    from .state import load_task_session

    sync_managed_document_protection(root_dir, load_task_session(root_dir))


def fuse_state(root_dir: Path) -> dict[str, Any]:
    """Return the current FUSE protection state for one workspace."""
    available = fuse_runtime_available()
    enabled = fuse_enabled(root_dir)
    runtime = fuse_status(root_dir) if available else {"running": False, "pid": None, "root": str(root_dir.resolve())}
    protection = "mounted" if enabled else "inactive" if available else "unavailable"
    return {
        "available": available,
        "enabled": enabled,
        "managed_root": str(managed_root_path(root_dir)),
        "runtime": runtime,
        "protection": protection,
    }


def public_fuse_status(root_dir: Path) -> dict[str, Any]:
    """Return the public-facing FUSE summary for agent-guard surfaces."""
    current = ensure_fuse_protection(root_dir)
    summary = {
        "protection": current["protection"],
    }
    if "reason" in current:
        summary["reason"] = current["reason"]
    if "started" in current:
        summary["started"] = current["started"]
    return summary


def ensure_fuse_protection(root_dir: Path) -> dict[str, Any]:
    """Start the workspace FUSE runtime when available and not already mounted."""
    current = fuse_state(root_dir)
    if current["enabled"]:
        _sync_workspace_protection(root_dir)
        return current
    if not current["available"]:
        return current

    runtime = current["runtime"]
    if bool(runtime.get("running")):
        return {
            **current,
            "protection": "desynced",
            "reason": "agent-guard-fuse is running but .agent is not mounted for this workspace.",
        }

    try:
        pid = start_fuse(root_dir)
    except RuntimeError as exc:
        return {
            **current,
            "protection": "error",
            "reason": str(exc),
        }

    refreshed = fuse_state(root_dir)
    if refreshed["enabled"]:
        _sync_workspace_protection(root_dir)
    return {
        **refreshed,
        "started": True,
        "pid": pid,
    }


def stop_fuse_protection(root_dir: Path) -> dict[str, Any]:
    """Stop the workspace FUSE runtime when it is running."""
    current = fuse_state(root_dir)
    if not current["available"]:
        return current
    stopped = stop_fuse(root_dir)
    refreshed = fuse_state(root_dir)
    return {
        **refreshed,
        "stopped": stopped,
    }
