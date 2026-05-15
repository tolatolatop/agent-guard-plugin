"""Tests for test state."""
from agent_guard.jobs import load_jobs
from agent_guard.state import (
    DEFAULT_JOBS,
    DEFAULT_STATE,
    ensure_agent_files,
    load_stage_artifact_snapshot,
    load_state,
    load_task_session,
    save_state,
)

from .helpers import make_temp_repo


def test_state_defaults_to_idle_when_agent_dir_is_missing() -> None:
    """Test that state defaults to idle when agent dir is missing."""
    root_dir = make_temp_repo()
    for child in (root_dir / ".agent").rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted((root_dir / ".agent").rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    (root_dir / ".agent").rmdir()

    assert load_state(root_dir) == DEFAULT_STATE
    assert load_jobs(root_dir) == DEFAULT_JOBS


def test_state_loads_defaults_after_init() -> None:
    """Test that state loads defaults after init."""
    root_dir = make_temp_repo()
    assert load_state(root_dir) == DEFAULT_STATE


def test_init_creates_agent_artifacts_directory() -> None:
    """Test that init creates agent artifacts directory."""
    root_dir = make_temp_repo()
    agent_dir = root_dir / ".agent"
    artifacts_dir = agent_dir / "artifacts"

    assert agent_dir.exists()
    assert artifacts_dir.exists()
    assert artifacts_dir.is_dir()

    extra_root = root_dir / "fresh-init"
    extra_root.mkdir()
    ensure_agent_files(extra_root)
    assert (extra_root / ".agent" / "artifacts").is_dir()


def test_state_saves_and_reloads_updates() -> None:
    """Test that state saves and reloads updates."""
    root_dir = make_temp_repo()
    next_state = {**DEFAULT_STATE, "stage": "RED_TEST", "current_step": "red-001"}
    save_state(root_dir, next_state)
    assert load_state(root_dir) == next_state


def test_state_loads_structured_task_session() -> None:
    """Test that state exposes a structured task session aggregate."""
    root_dir = make_temp_repo()
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "VERIFY"})

    session = load_task_session(root_dir)
    assert session.task_id == "password-reset"
    assert session.stage == "VERIFY"


def test_stage_artifact_snapshot_tracks_stage_entry() -> None:
    """Test that stage artifact snapshots are recorded when the stage changes."""
    root_dir = make_temp_repo()
    snapshot = load_stage_artifact_snapshot(root_dir)
    assert snapshot["stage"] == "IDLE"

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "REVIEW"})
    snapshot = load_stage_artifact_snapshot(root_dir)

    assert snapshot["stage"] == "REVIEW"
    assert snapshot["entered_at"] is not None
    assert ".agent/artifacts/review.md" in snapshot["artifacts"]
    assert snapshot["artifacts"][".agent/artifacts/review.md"]["mtime_ns"] is None
