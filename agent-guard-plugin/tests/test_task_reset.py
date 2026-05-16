"""Tests for test task reset."""
import json
from pathlib import Path
from unittest.mock import patch

from agent_guard.cli import run_command
from agent_guard.state import AGENT_DIR, load_state

from .helpers import make_temp_repo, write_state


def test_reset_task_requires_completed_state() -> None:
    """Test that reset task requires completed state."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="old-task", stage="GREEN_IMPL", current_step="green-001")

    try:
        run_command(["reset-task", "new-task"], root_dir)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("reset-task should have failed")


def test_reset_task_archives_current_records_and_initializes_new_task() -> None:
    """Test that reset task archives current records and initializes new task."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="old-task",
        stage="DONE",
        current_step="verify-001",
        can_finalize=True,
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-12T10:00:00Z",
        },
    )
    (root_dir / ".agent" / "events.jsonl").write_text('{"ts":"2026-05-12T10:00:00Z"}\n', encoding="utf-8")
    (root_dir / ".agent" / "plan.yaml").write_text("task_id: old-task\nsteps: []\n", encoding="utf-8")
    (root_dir / ".agent" / "artifacts" / "final-verification.log").write_text("ok\n", encoding="utf-8")

    try:
        run_command(["reset-task", "new-task"], root_dir)
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("reset-task should exit")

    state = load_state(root_dir)
    assert state["task_id"] == "new-task"
    assert state["stage"] == "CLARIFYING"
    assert state["can_finalize"] is False

    archive_root = root_dir / AGENT_DIR / "archive"
    archived_dirs = list(archive_root.iterdir())
    assert len(archived_dirs) == 1
    archive_dir = archived_dirs[0]

    snapshot = json.loads((archive_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["state"]["task_id"] == "old-task"
    assert (archive_dir / "events.jsonl").exists()
    assert (archive_dir / "plan.yaml").exists()
    assert (archive_dir / "artifacts" / "final-verification.log").exists()

    assert (root_dir / ".agent" / "events.jsonl").read_text(encoding="utf-8") == ""
    assert not (root_dir / ".agent" / "plan.yaml").exists()
    assert not list((root_dir / ".agent" / "artifacts").iterdir())


def test_close_task_requires_completed_state_without_force() -> None:
    """close-task should reject in-progress tasks by default."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="old-task", stage="GREEN_IMPL", current_step="green-001")

    try:
        run_command(["close-task"], root_dir)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("close-task should have failed")


def test_close_task_stops_workspace_protection_for_completed_task() -> None:
    """close-task should stop workspace protection after completion."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="old-task",
        stage="DONE",
        current_step=None,
        can_finalize=True,
        fuse="enabled",
    )

    with (
        patch(
            "agent_guard.task_reset.stop_fuse_protection",
            return_value={"protection": "inactive", "stopped": True},
        ) as stop_protection,
    ):
        try:
            run_command(["close-task"], root_dir)
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("close-task should exit")

    stop_protection.assert_called_once_with(root_dir)


def test_close_task_force_stops_workspace_protection_for_in_progress_task() -> None:
    """close-task --force should stop protection even before DONE."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="old-task", stage="GREEN_IMPL", current_step="green-001")

    with (
        patch(
            "agent_guard.task_reset.stop_fuse_protection",
            return_value={"protection": "inactive", "stopped": True},
        ) as stop_protection,
    ):
        try:
            run_command(["close-task", "--force"], root_dir)
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("close-task --force should exit")

    stop_protection.assert_called_once_with(root_dir)
