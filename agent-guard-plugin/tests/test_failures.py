"""Tests for test failures."""
from pathlib import Path

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


def test_success_command_without_log_only_records_event() -> None:
    """Test that success command without log only records event."""
    root_dir = make_temp_repo()
    write_state(root_dir, stage="GREEN_IMPL")

    result = record_command_result(root_dir, "pytest tests/example.py", 0, None)

    assert result["failure"] is None
    assert "log_path" not in result["event"]
