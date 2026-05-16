"""Persistent workflow state helpers under the .agent directory."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .domain.models import TaskSession
from agent_guard_file_lock import read_protected_text, resolve_protected_path, write_protected_text

AGENT_DIR = ".agent"
ARTIFACTS_DIR = f"{AGENT_DIR}/artifacts"

DEFAULT_STATE: dict[str, Any] = {
    "state_id": None,
    "task_id": None,
    "workflow_id": None,
    "stage": "IDLE",
    "current_step": None,
    "can_finalize": False,
    "last_verification": None,
    "needs_human": False,
    "fuse": "disabled",
}

DEFAULT_JOBS: dict[str, Any] = {"jobs": []}
DEFAULT_FAILURES: dict[str, Any] = {"last_failure": None}
DEFAULT_STAGE_ARTIFACTS: dict[str, Any] = {
    "stage": "IDLE",
    "entered_at": None,
    "artifacts": {},
}


def _state_file_error(file_path: Path, detail: str) -> RuntimeError:
    """Build a user-facing state corruption error."""
    return RuntimeError(
        f"{file_path.name} appears damaged at {file_path}. {detail} "
        "The current task cannot continue until this file is repaired or restored."
    )


def agent_dir(root_dir: Path) -> Path:
    """Agent dir."""
    return root_dir / AGENT_DIR


def artifacts_dir(root_dir: Path) -> Path:
    """Artifacts dir."""
    return root_dir / ARTIFACTS_DIR


def managed_state_root() -> Path:
    """Global state storage root."""
    return Path.home() / ".agent-guard" / "state"


def managed_state_dir(state_id: str) -> Path:
    """Global state storage directory for one state id."""
    return managed_state_root() / state_id


def current_managed_state_dir(root_dir: Path) -> Path:
    """Global state directory for the current workspace state."""
    state = load_state(root_dir)
    state_id = str(state["state_id"])
    target = managed_state_dir(state_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def state_path(root_dir: Path) -> Path:
    """State path."""
    return agent_dir(root_dir) / "state.json"


def jobs_path(root_dir: Path) -> Path:
    """Jobs path."""
    return agent_dir(root_dir) / "jobs.json"


def failures_path(root_dir: Path) -> Path:
    """Failures path."""
    return agent_dir(root_dir) / "failures.json"


def events_path(root_dir: Path) -> Path:
    """Events path."""
    return agent_dir(root_dir) / "events.jsonl"


def stage_artifacts_path(root_dir: Path) -> Path:
    """Stage artifact snapshot path."""
    return agent_dir(root_dir) / "stage-artifacts.json"


def _artifact_mtime_ns(root_dir: Path, artifact_path: str) -> int | None:
    candidate = root_dir / artifact_path
    if not candidate.exists():
        return None
    return int(candidate.stat().st_mtime_ns)


def record_stage_artifact_snapshot(root_dir: Path, stage: str, workflow_id: str | None = None) -> dict[str, Any]:
    """Record stage entry time and required artifact mtimes for later exit checks."""
    from .workflow_spec import stage_required_artifacts

    snapshot = {
        "stage": stage,
        "entered_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            artifact_path: {"mtime_ns": _artifact_mtime_ns(root_dir, artifact_path)}
            for artifact_path in stage_required_artifacts(stage, root_dir, workflow_id)
        },
    }
    write_protected_text(
        root_dir,
        ".agent/stage-artifacts.json",
        json.dumps(snapshot, indent=2) + "\n",
        encoding="utf-8",
        enforce_lock=False,
    )
    return snapshot


def load_stage_artifact_snapshot(root_dir: Path) -> dict[str, Any]:
    """Load the current stage artifact snapshot."""
    file_path = stage_artifacts_path(root_dir)
    if not file_path.exists():
        return DEFAULT_STAGE_ARTIFACTS.copy()
    payload = read_json(file_path, "stage-artifacts.json")
    artifacts = payload.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise RuntimeError("stage-artifacts.json artifacts must be a JSON object.")
    return {
        "stage": str(payload.get("stage") or "IDLE"),
        "entered_at": payload.get("entered_at"),
        "artifacts": {
            str(path): {
                "mtime_ns": None if details is None else details.get("mtime_ns"),
            }
            for path, details in artifacts.items()
        },
    }


def ensure_stage_artifact_snapshot(root_dir: Path, stage: str, workflow_id: str | None = None) -> dict[str, Any]:
    """Ensure the snapshot file exists for the current stage."""
    current = load_stage_artifact_snapshot(root_dir)
    if current.get("stage") == stage and stage_artifacts_path(root_dir).exists():
        return current
    return record_stage_artifact_snapshot(root_dir, stage, workflow_id)


def _write_json_if_missing(file_path: Path, value: dict[str, Any]) -> None:
    """Internal helper for write json if missing."""
    if not file_path.exists():
        write_protected_text(
            file_path.parent.parent,
            file_path.relative_to(file_path.parent.parent).as_posix(),
            json.dumps(value, indent=2) + "\n",
            encoding="utf-8",
            enforce_lock=False,
        )


def _next_state_id() -> str:
    """Generate a stable new state id."""
    return uuid4().hex


def ensure_managed_state_dir(state_id: str | None) -> Path | None:
    """Ensure the global state directory exists for one state id."""
    if not state_id:
        return None
    target = managed_state_dir(state_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_agent_files(root_dir: Path) -> None:
    # Create the full managed workspace up front so later commands can assume
    # .agent state, artifacts, and event files exist.
    """Ensure agent files."""
    artifacts_dir(root_dir).mkdir(parents=True, exist_ok=True)
    _write_json_if_missing(state_path(root_dir), DEFAULT_STATE)
    _write_json_if_missing(jobs_path(root_dir), DEFAULT_JOBS)
    _write_json_if_missing(failures_path(root_dir), DEFAULT_FAILURES)
    if not events_path(root_dir).exists():
        events_path(root_dir).write_text("", encoding="utf-8")
    if not stage_artifacts_path(root_dir).exists():
        record_stage_artifact_snapshot(root_dir, str(DEFAULT_STATE["stage"]), None)


def read_json(file_path: Path, label: str) -> dict[str, Any]:
    """Read json."""
    root_dir = file_path.parent.parent
    actual_path = resolve_protected_path(root_dir, file_path.relative_to(root_dir).as_posix())
    if not actual_path.exists():
        raise RuntimeError(f"{label} is missing at {file_path}. Run agent-guard init first.")
    try:
        value = json.loads(read_protected_text(root_dir, file_path.relative_to(root_dir).as_posix(), encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _state_file_error(file_path, f"JSON parsing failed: {exc}.") from exc
    if not isinstance(value, dict):
        raise _state_file_error(file_path, "The top-level JSON value must be an object.")
    return value


def validate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Validate state."""
    required_keys = [
        "task_id",
        "stage",
        "current_step",
        "can_finalize",
        "last_verification",
        "needs_human",
    ]
    for key in required_keys:
        if key not in state:
            raise RuntimeError(
                f"state.json appears damaged. Missing required key: {key}. "
                "The current task cannot continue until .agent/state.json is repaired or restored."
            )
    state.setdefault("state_id", None)
    if not isinstance(state.get("state_id"), str) or not str(state.get("state_id")).strip():
        state["state_id"] = _next_state_id()
    state.setdefault("workflow_id", None)
    state.setdefault("fuse", "disabled")
    state.pop("completed_steps", None)
    state.pop("remaining_steps", None)
    state.pop("allowed_paths", None)
    state.pop("forbidden_paths", None)
    return state


def load_task_session(root_dir: Path) -> TaskSession:
    """Load the structured task session aggregate."""
    return TaskSession.from_mapping(load_state(root_dir))


def save_task_session(root_dir: Path, session: TaskSession) -> TaskSession:
    """Persist the structured task session aggregate."""
    return TaskSession.from_mapping(save_state(root_dir, session.to_mapping()))


def load_state(root_dir: Path) -> dict[str, Any]:
    """Load state."""
    file_path = state_path(root_dir)
    actual_path = resolve_protected_path(root_dir, file_path.relative_to(root_dir).as_posix())
    if not actual_path.exists():
        validated = validate_state(DEFAULT_STATE.copy())
        ensure_managed_state_dir(str(validated.get("state_id")))
        return validated
    raw = read_json(file_path, "state.json")
    raw_before = dict(raw)
    validated = validate_state(raw)
    ensure_managed_state_dir(str(validated.get("state_id")))
    if validated != raw_before:
        write_protected_text(
            root_dir,
            ".agent/state.json",
            json.dumps(validated, indent=2) + "\n",
            encoding="utf-8",
            enforce_lock=False,
        )
    return validated


def save_state(root_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Save state."""
    file_path = state_path(root_dir)
    actual_path = resolve_protected_path(root_dir, file_path.relative_to(root_dir).as_posix())
    if (not isinstance(state.get("state_id"), str) or not str(state.get("state_id")).strip()) and actual_path.exists():
        try:
            existing_state_id = read_json(file_path, "state.json").get("state_id")
        except RuntimeError:
            existing_state_id = None
        if isinstance(existing_state_id, str) and existing_state_id.strip():
            state = {**state, "state_id": existing_state_id}
    validated = validate_state(state)
    ensure_managed_state_dir(str(validated.get("state_id")))
    previous_stage: str | None = None
    if actual_path.exists():
        try:
            previous_stage = str(read_json(file_path, "state.json").get("stage") or "IDLE")
        except RuntimeError:
            previous_stage = None
    write_protected_text(
        root_dir,
        ".agent/state.json",
        json.dumps(validated, indent=2) + "\n",
        encoding="utf-8",
        enforce_lock=False,
    )
    current_stage = str(validated.get("stage") or "IDLE")
    if previous_stage != current_stage or not stage_artifacts_path(root_dir).exists():
        workflow_id = str(validated.get("workflow_id")) if isinstance(validated.get("workflow_id"), str) else None
        record_stage_artifact_snapshot(root_dir, current_stage, workflow_id)
    return validated


def update_state(root_dir: Path, updater: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Update state."""
    current = load_state(root_dir)
    return save_state(root_dir, updater(current))
