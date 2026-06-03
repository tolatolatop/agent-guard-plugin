"""Tests for test failures."""
from pathlib import Path

from agent_guard.domain.models import TaskSession
from agent_guard.failures import check_failure_loop, record_command_result
from agent_guard.state import load_state

from .helpers import make_temp_repo, write_state


def test_record_command_moves_stage_to_failure_analysis_outside_red_test() -> None:
    """Test that record command moves stage to failure analysis outside red test."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="GREEN_IMPL")

    log_path = ".agent/artifacts/green-test.log"
    (root_dir / log_path).write_text("expected failure\n", encoding="utf-8")

    result = record_command_result(root_dir, "pytest", 1, log_path)
    assert result["failure"]["command"] == "pytest"
    assert load_state(root_dir)["stage"] == "NEEDS_FAILURE_ANALYSIS"


def test_repeating_same_failed_command_twice_without_code_changes_is_blocked() -> None:
    """Test that repeating same failed command twice without code changes is blocked."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="GREEN_IMPL")

    log_path = ".agent/artifacts/red-test.log"
    (root_dir / log_path).write_text("same failure\n", encoding="utf-8")

    record_command_result(root_dir, "pytest tests/example.py", 1, log_path)
    record_command_result(root_dir, "pytest tests/example.py", 1, log_path)

    result = check_failure_loop(root_dir)
    assert result["decision"] == "block"
    assert "failure analysis" in result["reason"].lower()


def test_verify_command_records_final_verification_result() -> None:
    """Test that verify command records final verification result."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="VERIFY")

    log_path = ".agent/artifacts/final-verification.log"
    (root_dir / log_path).write_text("all green\n", encoding="utf-8")

    record_command_result(root_dir, "pytest", 0, log_path)
    state = load_state(root_dir)
    assert state["last_verification"]["exit_code"] == 0


def test_failed_green_impl_command_keeps_event_stage_as_execution_stage() -> None:
    """Failed commands should be attributed to the stage where they ran, not the escalated stage."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="GREEN_IMPL")

    log_path = ".agent/artifacts/green-test.log"
    (root_dir / log_path).write_text("expected failure\n", encoding="utf-8")

    result = record_command_result(root_dir, "pytest", 1, log_path)

    assert result["state"]["stage"] == "NEEDS_FAILURE_ANALYSIS"
    assert result["event"]["stage"] == "GREEN_IMPL"


def test_failed_verify_command_records_verification_and_keeps_event_stage() -> None:
    """Verification commands should keep their original stage in the event log even when they escalate."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="VERIFY")

    log_path = ".agent/artifacts/final-verification.log"
    (root_dir / log_path).write_text("boom\n", encoding="utf-8")

    result = record_command_result(root_dir, "pytest", 1, log_path)
    state = load_state(root_dir)

    assert result["state"]["stage"] == "NEEDS_FAILURE_ANALYSIS"
    assert result["event"]["stage"] == "VERIFY"
    assert state["last_verification"]["command"] == "pytest"
    assert state["last_verification"]["exit_code"] == 1


def test_success_command_without_log_only_records_event() -> None:
    """Test that success command without log only records event."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="GREEN_IMPL")

    result = record_command_result(root_dir, "pytest tests/example.py", 0, None)

    assert result["failure"] is None
    assert "log_path" not in result["event"]


def test_failed_command_fingerprint_skips_broken_symlinks() -> None:
    """Broken symlinks under fingerprint roots should not crash hook handling."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="GREEN_IMPL")
    (root_dir / "src").mkdir()
    (root_dir / "src" / "broken-link").symlink_to("missing-target")
    log_path = ".agent/artifacts/green-test.log"
    (root_dir / log_path).write_text("boom\n", encoding="utf-8")

    result = record_command_result(root_dir, "pytest", 1, log_path)

    assert result["failure"]["command"] == "pytest"
    assert load_state(root_dir)["stage"] == "NEEDS_FAILURE_ANALYSIS"


def test_task_session_advance_clears_needs_human_after_escalation_stage() -> None:
    """Test that advancing from an escalation stage clears needs_human."""
    session = TaskSession(
        task_id="password-reset",
        workflow_id=None,
        stage="NEEDS_HUMAN",
        current_step="green-001",
        needs_human=True,
    )

    next_session = session.advance_to("GREEN_IMPL", current_step="green-001")

    assert next_session.stage == "GREEN_IMPL"
    assert next_session.needs_human is False
