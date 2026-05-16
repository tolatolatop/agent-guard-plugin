"""Tests for repository boundary behavior."""
from __future__ import annotations

from agent_guard.domain.models import TaskSession
from agent_guard.infrastructure.repositories import StateRepository

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

    StateRepository(root_dir).save(session)
    loaded = StateRepository(root_dir).load()

    assert loaded == session
