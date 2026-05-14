"""Persistent workflow state helpers under the .agent directory."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .domain.models import TaskSession

AGENT_DIR = ".agent"
ARTIFACTS_DIR = f"{AGENT_DIR}/artifacts"

DEFAULT_STATE: dict[str, Any] = {
    "task_id": None,
    "stage": "IDLE",
    "current_step": None,
    "completed_steps": [],
    "remaining_steps": [],
    "can_finalize": False,
    "last_verification": None,
    "needs_human": False,
}

DEFAULT_JOBS: dict[str, Any] = {"jobs": []}
DEFAULT_FAILURES: dict[str, Any] = {"last_failure": None}
DEFAULT_STAGE_ARTIFACTS: dict[str, Any] = {
    "stage": "IDLE",
    "entered_at": None,
    "artifacts": {},
}


def agent_dir(root_dir: Path) -> Path:
    """Agent dir."""
    return root_dir / AGENT_DIR


def artifacts_dir(root_dir: Path) -> Path:
    """Artifacts dir."""
    return root_dir / ARTIFACTS_DIR


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


def record_stage_artifact_snapshot(root_dir: Path, stage: str) -> dict[str, Any]:
    """Record stage entry time and required artifact mtimes for later exit checks."""
    from .workflow_spec import stage_required_artifacts

    snapshot = {
        "stage": stage,
        "entered_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            artifact_path: {"mtime_ns": _artifact_mtime_ns(root_dir, artifact_path)}
            for artifact_path in stage_required_artifacts(stage)
        },
    }
    stage_artifacts_path(root_dir).write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
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


def ensure_stage_artifact_snapshot(root_dir: Path, stage: str) -> dict[str, Any]:
    """Ensure the snapshot file exists for the current stage."""
    current = load_stage_artifact_snapshot(root_dir)
    if current.get("stage") == stage and stage_artifacts_path(root_dir).exists():
        return current
    return record_stage_artifact_snapshot(root_dir, stage)


def required_artifact_exit_failures(root_dir: Path, stage: str) -> list[str]:
    """Return required-artifact exit failures for the current stage."""
    from .workflow_spec import stage_required_artifacts

    required = stage_required_artifacts(stage)
    if not required:
        return []

    snapshot = ensure_stage_artifact_snapshot(root_dir, stage)
    entered_at = snapshot.get("entered_at") or "the current stage"
    recorded = snapshot.get("artifacts", {})
    failures: list[str] = []
    for artifact_path in required:
        current_mtime = _artifact_mtime_ns(root_dir, artifact_path)
        previous_mtime = None
        details = recorded.get(artifact_path)
        if isinstance(details, dict):
            previous_mtime = details.get("mtime_ns")
        if current_mtime is None:
            failures.append(f"{artifact_path} must exist and be updated after entering {stage} at {entered_at}.")
            continue
        if previous_mtime is not None and int(current_mtime) <= int(previous_mtime):
            failures.append(f"{artifact_path} must be updated after entering {stage} at {entered_at}.")
    return failures


def _write_json_if_missing(file_path: Path, value: dict[str, Any]) -> None:
    """Internal helper for write json if missing."""
    if not file_path.exists():
        file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


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
        record_stage_artifact_snapshot(root_dir, str(DEFAULT_STATE["stage"]))


def read_json(file_path: Path, label: str) -> dict[str, Any]:
    """Read json."""
    if not file_path.exists():
        raise RuntimeError(f"{label} is missing at {file_path}. Run agent-guard init first.")
    try:
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must contain a JSON object.")
    return value


def validate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Validate state."""
    required_keys = [
        "task_id",
        "stage",
        "current_step",
        "completed_steps",
        "remaining_steps",
        "can_finalize",
        "last_verification",
        "needs_human",
    ]
    for key in required_keys:
        if key not in state:
            raise RuntimeError(f"state.json is missing required key: {key}")
    state.pop("allowed_paths", None)
    state.pop("forbidden_paths", None)
    return state


def load_task_session(root_dir: Path) -> TaskSession:
    """Load the structured task session aggregate."""
    return TaskSession.from_mapping(load_state(root_dir))


def save_task_session(root_dir: Path, session: TaskSession) -> TaskSession:
    """Persist the structured task session aggregate."""
    save_state(root_dir, session.to_mapping())
    return session


def load_state(root_dir: Path) -> dict[str, Any]:
    """Load state."""
    file_path = state_path(root_dir)
    if not file_path.exists():
        return DEFAULT_STATE.copy()
    return validate_state(read_json(file_path, "state.json"))


def save_state(root_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Save state."""
    validated = validate_state(state)
    previous_stage: str | None = None
    file_path = state_path(root_dir)
    if file_path.exists():
        try:
            previous_stage = str(read_json(file_path, "state.json").get("stage") or "IDLE")
        except RuntimeError:
            previous_stage = None
    file_path.write_text(json.dumps(validated, indent=2) + "\n", encoding="utf-8")
    current_stage = str(validated.get("stage") or "IDLE")
    if previous_stage != current_stage or not stage_artifacts_path(root_dir).exists():
        record_stage_artifact_snapshot(root_dir, current_stage)
    return validated


def update_state(root_dir: Path, updater: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Update state."""
    current = load_state(root_dir)
    return save_state(root_dir, updater(current))
