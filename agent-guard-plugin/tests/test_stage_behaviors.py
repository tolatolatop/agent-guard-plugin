"""Stage-level behavior tests with mocked collaborators."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent_guard.application.use_cases import start_task
from agent_guard.domain.models import TaskSession
from agent_guard.runtime_bridge import _handle_post_command, _handle_stop
from agent_guard.transitions import _guard_transition, complete_step, mark_done

from .helpers import make_temp_repo


def test_idle_start_task_uses_canonical_entry_stage() -> None:
    """IDLE: start-task should use the canonical entry stage."""
    root_dir = make_temp_repo()
    session = TaskSession(task_id=None, workflow_id=None, stage="IDLE", current_step=None)
    repo = Mock()
    repo.load.return_value = session
    repo.save.side_effect = lambda updated: updated

    with (
        patch("agent_guard.application.use_cases.ensure_agent_files"),
        patch("agent_guard.application.use_cases.StateRepository", return_value=repo),
        patch("agent_guard.application.use_cases.canonical_entry_stage", return_value="CLARIFYING"),
    ):
        result = start_task(root_dir, "password-reset")

    assert result["state"]["stage"] == "CLARIFYING"
    assert result["state"]["task_id"] == "password-reset"


def test_active_start_task_does_not_recompute_entry_stage() -> None:
    """Active tasks should be handled by the aggregate without consulting workflow entry stage."""
    root_dir = make_temp_repo()
    session = TaskSession(task_id="market-scan", workflow_id="research", stage="QUESTIONING", current_step="question-001")
    repo = Mock()
    repo.load.return_value = session
    repo.save.side_effect = lambda updated: updated

    with (
        patch("agent_guard.application.use_cases.ensure_agent_files"),
        patch("agent_guard.application.use_cases.StateRepository", return_value=repo),
        patch("agent_guard.application.use_cases.canonical_entry_stage") as canonical_entry_stage,
    ):
        with pytest.raises(RuntimeError) as exc:
            start_task(root_dir, "market-scan", workflow_id="coding")

    canonical_entry_stage.assert_not_called()
    assert "different workflow" in str(exc.value)


def test_clarifying_stop_allows_without_finalize_check() -> None:
    """CLARIFYING: stop should be allowed immediately."""
    root_dir = make_temp_repo()

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "CLARIFYING", "can_finalize": False}),
        patch("agent_guard.runtime_bridge.stage_forbid_needs_human_display", return_value=None),
        patch("agent_guard.runtime_bridge.canonical_stage_stop_allowed", return_value=True),
        patch("agent_guard.runtime_bridge._cli_json") as cli_json,
    ):
        with pytest.raises(SystemExit) as exc:
            _handle_stop(root_dir)

    assert exc.value.code == 0
    cli_json.assert_not_called()


def test_designing_stop_blocks_with_stage_message() -> None:
    """DESIGNING: stop should be blocked by the stage handoff rule."""
    root_dir = make_temp_repo()

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "DESIGNING", "can_finalize": False}),
        patch(
            "agent_guard.runtime_bridge.stage_forbid_needs_human_display",
            return_value="Current stage does not allow human intervention; continue advancing the task.",
        ),
        patch("agent_guard.runtime_bridge._fail", side_effect=RuntimeError("blocked")) as fail,
    ):
        with pytest.raises(RuntimeError):
            _handle_stop(root_dir)

    fail.assert_called_once()
    assert "Current stage does not allow human intervention" in fail.call_args.args[2]


def test_planning_stop_allows_without_finalize_check() -> None:
    """PLANNING: stop should be allowed immediately."""
    root_dir = make_temp_repo()

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "PLANNING", "can_finalize": False}),
        patch("agent_guard.runtime_bridge.stage_forbid_needs_human_display", return_value=None),
        patch("agent_guard.runtime_bridge.canonical_stage_stop_allowed", return_value=True),
        patch("agent_guard.runtime_bridge._cli_json") as cli_json,
    ):
        with pytest.raises(SystemExit) as exc:
            _handle_stop(root_dir)

    assert exc.value.code == 0
    cli_json.assert_not_called()


def test_red_test_post_command_records_red_test_log() -> None:
    """RED_TEST: failing commands should be logged to red-test.log."""
    root_dir = make_temp_repo()
    payload = {
        "tool_input": {"command": "pytest tests/example.py"},
        "tool_response": {"exit_code": 1, "stdout": "boom", "stderr": ""},
    }

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "RED_TEST"}),
        patch("agent_guard.runtime_bridge.canonical_verification_stage", return_value="VERIFY"),
        patch("agent_guard.runtime_bridge.canonical_expected_failure_stage", return_value="RED_TEST"),
        patch("agent_guard.runtime_bridge._write_command_log", return_value=".agent/artifacts/red-test.log") as write_log,
        patch("agent_guard.runtime_bridge._cli_json", return_value=(0, {})) as cli_json,
    ):
        _handle_post_command(root_dir, payload)

    write_log.assert_called_once()
    args = cli_json.call_args.args[0]
    assert args[:5] == ["record-command", "--cmd", "pytest tests/example.py", "--exit-code", "1"]
    assert args[-2:] == ["--log", ".agent/artifacts/red-test.log"]


def test_green_impl_post_command_skips_success_log() -> None:
    """GREEN_IMPL: successful commands should not write a stage log."""
    root_dir = make_temp_repo()
    payload = {
        "tool_input": {"command": "pytest tests/example.py"},
        "tool_response": {"exit_code": 0, "stdout": "ok", "stderr": ""},
    }

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "GREEN_IMPL"}),
        patch("agent_guard.runtime_bridge.canonical_verification_stage", return_value="VERIFY"),
        patch("agent_guard.runtime_bridge.canonical_expected_failure_stage", return_value="RED_TEST"),
        patch("agent_guard.runtime_bridge._write_command_log") as write_log,
        patch("agent_guard.runtime_bridge._cli_json", return_value=(0, {})) as cli_json,
    ):
        _handle_post_command(root_dir, payload)

    write_log.assert_not_called()
    assert "--log" not in cli_json.call_args.args[0]


def test_review_complete_step_preserves_review_stage() -> None:
    """REVIEW: complete-step should keep the session in REVIEW."""
    root_dir = make_temp_repo()
    session = TaskSession(task_id="password-reset", workflow_id=None, stage="REVIEW", current_step="review-001")

    with (
        patch("agent_guard.transitions.load_task_session", return_value=session),
        patch("agent_guard.transitions.complete_step_allowed_from_stages", return_value=["REVIEW"]),
        patch("agent_guard.transitions.update_plan_step_status") as update_status,
        patch("agent_guard.transitions.save_task_session") as save_session,
        patch("agent_guard.transitions._append_transition_event", return_value={"hook": "WorkflowTransition"}),
        patch("agent_guard.transitions._plan_step_goal", return_value=None),
    ):
        result = complete_step(root_dir, "review-001", next_step_id="verify-001")

    update_status.assert_called_once_with(root_dir, "review-001", "done")
    saved_session = save_session.call_args.args[1]
    assert saved_session.stage == "REVIEW"
    assert result["state"]["current_step"] == "verify-001"


def test_verify_post_command_records_final_verification_log() -> None:
    """VERIFY: successful commands should be logged to final-verification.log."""
    root_dir = make_temp_repo()
    payload = {
        "tool_input": {"command": "pytest"},
        "tool_response": {"exit_code": 0, "stdout": "ok", "stderr": ""},
    }

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "VERIFY"}),
        patch("agent_guard.runtime_bridge.canonical_verification_stage", return_value="VERIFY"),
        patch("agent_guard.runtime_bridge.canonical_expected_failure_stage", return_value="RED_TEST"),
        patch("agent_guard.runtime_bridge._write_command_log", return_value=".agent/artifacts/final-verification.log") as write_log,
        patch("agent_guard.runtime_bridge._cli_json", return_value=(0, {})) as cli_json,
    ):
        _handle_post_command(root_dir, payload)

    write_log.assert_called_once()
    assert cli_json.call_args.args[0][-2:] == ["--log", ".agent/artifacts/final-verification.log"]


def test_ready_to_summarize_mark_done_targets_completion_stage() -> None:
    """READY_TO_SUMMARIZE: mark-done should target the canonical completion stage."""
    root_dir = make_temp_repo()
    session = TaskSession(task_id="password-reset", workflow_id=None, stage="READY_TO_SUMMARIZE", current_step=None, can_finalize=True)

    with (
        patch("agent_guard.transitions.load_task_session", return_value=session),
        patch("agent_guard.transitions._guard_transition") as guard,
        patch("agent_guard.transitions.save_task_session") as save_session,
        patch("agent_guard.transitions._append_transition_event", return_value={"hook": "WorkflowTransition"}),
        patch("agent_guard.transitions.canonical_completion_stage", return_value="DONE"),
        patch("agent_guard.transitions._next_stages", return_value=[]),
    ):
        result = mark_done(root_dir)

    guard.assert_called_once_with(root_dir, session, "DONE", "mark-done", None)
    assert save_session.call_args.args[1].stage == "DONE"
    assert result["state"]["stage"] == "DONE"
    assert result["next_stages"] == []


def test_needs_failure_analysis_exit_guard_checks_artifacts() -> None:
    """NEEDS_FAILURE_ANALYSIS: transition guard should enforce exit artifacts."""
    root_dir = make_temp_repo()
    session = TaskSession(task_id="password-reset", workflow_id=None, stage="NEEDS_FAILURE_ANALYSIS", current_step="green-001")

    with (
        patch("agent_guard.transitions.STAGE_TRANSITIONS", {"NEEDS_FAILURE_ANALYSIS": ["VERIFY"], "VERIFY": []}),
        patch("agent_guard.transitions.canonical_completion_stage", return_value="DONE"),
        patch("agent_guard.transitions.StageExitPolicyService") as policy_service,
    ):
        policy_service.return_value.exit_failures.return_value = ["failure-analysis.md must be updated"]
        with pytest.raises(RuntimeError) as exc:
            _guard_transition(root_dir, session, "VERIFY", "advance-stage", "green-001")

    assert "failure-analysis.md must be updated" in str(exc.value)
    policy_service.return_value.exit_failures.assert_called_once_with("NEEDS_FAILURE_ANALYSIS")


def test_needs_human_stop_allows_without_finalize_check() -> None:
    """NEEDS_HUMAN: stop should be allowed immediately."""
    root_dir = make_temp_repo()

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "NEEDS_HUMAN", "can_finalize": False}),
        patch("agent_guard.runtime_bridge.stage_forbid_needs_human_display", return_value=None),
        patch("agent_guard.runtime_bridge.canonical_stage_stop_allowed", return_value=True),
        patch("agent_guard.runtime_bridge._cli_json") as cli_json,
    ):
        with pytest.raises(SystemExit) as exc:
            _handle_stop(root_dir)

    assert exc.value.code == 0
    cli_json.assert_not_called()


def test_done_stop_allows_without_finalize_check() -> None:
    """DONE: stop should be allowed immediately."""
    root_dir = make_temp_repo()

    with (
        patch("agent_guard.runtime_bridge.load_state", return_value={"stage": "DONE", "can_finalize": False}),
        patch("agent_guard.runtime_bridge.stage_forbid_needs_human_display", return_value=None),
        patch("agent_guard.runtime_bridge.canonical_stage_stop_allowed", return_value=True),
        patch("agent_guard.runtime_bridge._cli_json") as cli_json,
    ):
        with pytest.raises(SystemExit) as exc:
            _handle_stop(root_dir)

    assert exc.value.code == 0
    cli_json.assert_not_called()
