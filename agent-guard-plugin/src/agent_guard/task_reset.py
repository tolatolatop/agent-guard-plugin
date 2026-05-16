"""Task archival and reset helpers for starting the next task."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import (
    AGENT_DIR,
    DEFAULT_FAILURES,
    DEFAULT_JOBS,
    DEFAULT_STATE,
    agent_dir,
    artifacts_dir,
    ensure_agent_files,
    events_path,
    failures_path,
    jobs_path,
    load_state,
    save_state,
    state_path,
)
from .workflow_spec import canonical_completion_ready_stage, canonical_completion_stage, canonical_entry_stage


def _slugify(value: str) -> str:
    """Internal helper for slugify."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return slug or "task"


def _archive_root(root_dir: Path) -> Path:
    """Internal helper for archive root."""
    return agent_dir(root_dir) / "archive"


def _plan_path(root_dir: Path) -> Path:
    """Internal helper for plan path."""
    return agent_dir(root_dir) / "plan.yaml"


def _write_json(file_path: Path, value: dict[str, Any]) -> None:
    """Internal helper for write json."""
    file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def latest_archive(root_dir: Path) -> dict[str, Any] | None:
    """Return the latest archive."""
    archive_root = _archive_root(root_dir)
    if not archive_root.exists():
        return None

    candidates = [entry for entry in archive_root.iterdir() if entry.is_dir()]
    if not candidates:
        return None

    latest_dir = sorted(candidates)[-1]
    snapshot_path = latest_dir / "snapshot.json"
    archived_task_id = None
    if snapshot_path.exists():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        state = snapshot.get("state", {})
        if isinstance(state, dict):
            archived_task_id = state.get("task_id")

    return {
        "archive_dir": str(latest_dir),
        "archived_task_id": archived_task_id,
    }


def _is_resettable_state(root_dir: Path, state: dict[str, Any]) -> bool:
    """Internal helper for is resettable state."""
    workflow_id = str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None
    if state.get("stage") == canonical_completion_stage(root_dir, workflow_id):
        return True
    return state.get("stage") == canonical_completion_ready_stage(root_dir, workflow_id) and state.get("can_finalize") is True


def _snapshot_state(root_dir: Path) -> dict[str, Any]:
    """Internal helper for snapshot state."""
    snapshot: dict[str, Any] = {
        "state": json.loads(state_path(root_dir).read_text(encoding="utf-8")),
        "jobs": json.loads(jobs_path(root_dir).read_text(encoding="utf-8")),
        "failures": json.loads(failures_path(root_dir).read_text(encoding="utf-8")),
    }
    plan_file = _plan_path(root_dir)
    if plan_file.exists():
        snapshot["plan"] = plan_file.read_text(encoding="utf-8")
    return snapshot


def archive_current_task(root_dir: Path) -> dict[str, Any]:
    """Archive current task."""
    ensure_agent_files(root_dir)
    state = load_state(root_dir)
    task_id = str(state.get("task_id") or "unset-task")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = _archive_root(root_dir) / f"{timestamp}-{_slugify(task_id)}"
    archive_dir.mkdir(parents=True, exist_ok=False)

    snapshot = _snapshot_state(root_dir)
    (archive_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    events_file = events_path(root_dir)
    if events_file.exists():
      shutil.copy2(events_file, archive_dir / "events.jsonl")

    plan_file = _plan_path(root_dir)
    if plan_file.exists():
        shutil.copy2(plan_file, archive_dir / "plan.yaml")

    live_artifacts = artifacts_dir(root_dir)
    archived_artifacts = archive_dir / "artifacts"
    archived_artifacts.mkdir(parents=True, exist_ok=True)
    for child in live_artifacts.iterdir():
        target = archived_artifacts / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)

    return {
        "archive_dir": str(archive_dir),
        "archived_task_id": task_id,
    }


def _reset_runtime_files(root_dir: Path, new_task_id: str, workflow_id: str | None) -> dict[str, Any]:
    """Internal helper for reset runtime files."""
    live_artifacts = artifacts_dir(root_dir)
    if live_artifacts.exists():
        for child in list(live_artifacts.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    _write_json(jobs_path(root_dir), DEFAULT_JOBS)
    _write_json(failures_path(root_dir), DEFAULT_FAILURES)
    events_path(root_dir).write_text("", encoding="utf-8")

    plan_file = _plan_path(root_dir)
    if plan_file.exists():
        plan_file.unlink()

    new_state = {
        **DEFAULT_STATE,
        "task_id": new_task_id,
        "workflow_id": workflow_id,
        "stage": canonical_entry_stage(root_dir, workflow_id),
    }
    save_state(root_dir, new_state)
    return new_state


def reset_task(root_dir: Path, new_task_id: str, workflow_id: str | None = None) -> dict[str, Any]:
    """Reset task."""
    ensure_agent_files(root_dir)
    state = load_state(root_dir)
    if not _is_resettable_state(root_dir, state):
        current_workflow = str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None
        raise RuntimeError(
            "reset-task is only allowed when the current task is complete. "
            f"Move the state to {canonical_completion_stage(root_dir, current_workflow)} or "
            f"{canonical_completion_ready_stage(root_dir, current_workflow)} with can_finalize=true first."
        )

    archive_result = archive_current_task(root_dir)
    next_workflow = workflow_id or (str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None)
    new_state = _reset_runtime_files(root_dir, new_task_id, next_workflow)
    return {
        "archive_dir": archive_result["archive_dir"],
        "archived_task_id": archive_result["archived_task_id"],
        "state": new_state,
    }
