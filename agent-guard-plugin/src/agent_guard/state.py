"""Persistent workflow state helpers under the .agent directory."""
from __future__ import annotations

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
    state_path(root_dir).write_text(json.dumps(validated, indent=2) + "\n", encoding="utf-8")
    return validated


def update_state(root_dir: Path, updater: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Update state."""
    current = load_state(root_dir)
    return save_state(root_dir, updater(current))
