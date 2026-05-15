"""Tests for test state."""
import os

from agent_guard.domain.policies import StageExitPolicyService
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


def test_state_drops_legacy_step_fields_when_loading_and_saving() -> None:
    """Test that legacy step fields are ignored on load and removed on save."""
    root_dir = make_temp_repo()
    legacy_state = {
        **DEFAULT_STATE,
        "task_id": "password-reset",
        "completed_steps": ["red-001"],
        "remaining_steps": ["green-001"],
    }
    save_state(root_dir, legacy_state)

    state = load_state(root_dir)
    assert "completed_steps" not in state
    assert "remaining_steps" not in state


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


def test_stage_exit_policy_service_reports_missing_stale_and_mismatched_artifacts() -> None:
    """Test that stage exit policy reports all required-artifact failure modes."""
    root_dir = make_temp_repo()
    service = StageExitPolicyService(root_dir)

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "REVIEW"})
    failures = service.exit_failures("REVIEW")
    assert any("must exist and be updated after entering REVIEW" in failure for failure in failures)

    review_artifact = root_dir / ".agent" / "artifacts" / "review.md"
    review_artifact.write_text("stale\n", encoding="utf-8")
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "GREEN_IMPL"})
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "REVIEW"})
    failures = service.exit_failures("REVIEW")
    assert any("must be updated after entering REVIEW" in failure for failure in failures)

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "NEEDS_FAILURE_ANALYSIS"})
    analysis_artifact = root_dir / ".agent" / "artifacts" / "failure-analysis.md"
    analysis_artifact.write_text("wrong header\n", encoding="utf-8")
    fresh_mtime = analysis_artifact.stat().st_mtime_ns + 1_000_000
    os.utime(analysis_artifact, ns=(fresh_mtime, fresh_mtime))
    failures = service.exit_failures("NEEDS_FAILURE_ANALYSIS")
    assert any("Failure Summary" in failure for failure in failures)
