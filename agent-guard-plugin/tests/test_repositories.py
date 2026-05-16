"""Tests for repository boundary behavior."""
from __future__ import annotations

import yaml

from agent_guard.domain.models import TaskSession
from agent_guard.infrastructure.repositories import PlanRepository, StateRepository
from agent_guard.state import save_state
from agent_guard_file_lock import load_locks

from .helpers import make_temp_repo


def test_state_repository_load_uses_validated_state_reader() -> None:
    """Repository loads should surface the same friendly corruption errors as state helpers."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "state.json").write_text('{"task_id": null}\n', encoding="utf-8")

    try:
        StateRepository(root_dir).load()
    except RuntimeError as exc:
        assert "appears damaged" in str(exc)
        assert "Missing required key" in str(exc)
    else:
        raise AssertionError("Expected repository load to validate state.json")


def test_state_repository_save_round_trips_task_session() -> None:
    """Repository save/load should preserve aggregate state through the state helpers."""
    root_dir = make_temp_repo()
    session = TaskSession(
        task_id="password-reset",
        workflow_id=None,
        stage="VERIFY",
        current_step="verify-001",
        can_finalize=False,
        needs_human=False,
    )

    saved = StateRepository(root_dir).save(session)
    loaded = StateRepository(root_dir).load()

    assert saved.state_id is not None
    assert loaded == saved


def test_plan_repository_blocks_system_write_when_workflow_stage_disallows_plan_updates() -> None:
    """Plan repository should respect the managed document workflow policy."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "workflow_id": None,
            "stage": "CLARIFYING",
            "current_step": None,
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    try:
        PlanRepository(root_dir).save_steps("password-reset", [])
    except RuntimeError as exc:
        assert "plan.yaml cannot be updated by agent-guard during CLARIFYING" in str(exc)
    else:
        raise AssertionError("Expected plan repository write to be blocked outside allowed stages")


def test_plan_repository_allows_complete_step_update_outside_planning() -> None:
    """Plan repository should still allow complete-step driven updates in execution stages."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "workflow_id": None,
            "stage": "RED_TEST",
            "current_step": "red-001",
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    plan_path = root_dir / ".agent" / "plan.yaml"
    plan_path.write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - id: red-001\n"
        "    goal: write failing test\n"
        "    status: in_progress\n",
        encoding="utf-8",
    )

    payload = PlanRepository(root_dir).update_step_status("red-001", "done")

    assert payload["steps"][0]["status"] == "done"
    assert yaml.safe_load(plan_path.read_text(encoding="utf-8"))["steps"][0]["status"] == "done"


def test_save_state_syncs_long_lived_managed_document_locks() -> None:
    """State persistence should keep the strategy lock set aligned with the workflow stage."""
    root_dir = make_temp_repo()

    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "workflow_id": None,
            "stage": "CLARIFYING",
            "current_step": None,
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    root_entry = load_locks()["roots"][str(root_dir.resolve())]
    assert root_entry["files"] == ["plan.yaml", "state.json"]

    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "workflow_id": None,
            "stage": "PLANNING",
            "current_step": None,
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    root_entry = load_locks()["roots"][str(root_dir.resolve())]
    assert root_entry["files"] == ["state.json"]
