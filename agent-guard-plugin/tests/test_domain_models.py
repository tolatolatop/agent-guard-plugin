"""Tests for core domain model invariants."""
from __future__ import annotations

from agent_guard.domain.models import TaskSession, VerificationRecord


def test_mark_ready_to_summarize_clears_step_and_enables_finalize() -> None:
    """The completion-ready transition should clear step focus and enable finalization."""
    session = TaskSession(
        task_id="password-reset",
        workflow_id="research",
        stage="VERIFY",
        current_step="verify-001",
        can_finalize=False,
    )

    next_session = session.mark_ready_to_summarize("READY_TO_SUMMARIZE")

    assert next_session.stage == "READY_TO_SUMMARIZE"
    assert next_session.current_step is None
    assert next_session.can_finalize is True
    assert next_session.workflow_id == "research"


def test_enter_failure_analysis_preserves_step_and_disables_finalize() -> None:
    """Failure escalation should keep execution context but turn off finalization."""
    session = TaskSession(
        task_id="password-reset",
        workflow_id=None,
        stage="GREEN_IMPL",
        current_step="green-001",
        can_finalize=True,
    )

    next_session = session.enter_failure_analysis()

    assert next_session.stage == "NEEDS_FAILURE_ANALYSIS"
    assert next_session.current_step == "green-001"
    assert next_session.can_finalize is False


def test_advance_to_needs_human_sets_flag_and_resume_clears_it() -> None:
    """Human escalation is a session fact that should clear when normal work resumes."""
    session = TaskSession(
        task_id="password-reset",
        workflow_id=None,
        stage="REVIEW",
        current_step="review-001",
        needs_human=False,
    )

    needs_human = session.enter_needs_human()
    resumed = needs_human.advance_to("VERIFY", current_step="verify-001")

    assert needs_human.stage == "NEEDS_HUMAN"
    assert needs_human.needs_human is True
    assert resumed.stage == "VERIFY"
    assert resumed.current_step == "verify-001"
    assert resumed.needs_human is False


def test_record_verification_replaces_last_verification_without_mutating_stage() -> None:
    """Verification evidence is session state, not a stage transition by itself."""
    session = TaskSession(
        task_id="password-reset",
        workflow_id=None,
        stage="VERIFY",
        current_step="verify-001",
    )
    record = VerificationRecord(command="pytest", exit_code=0, log_path=".agent/artifacts/final-verification.log")

    next_session = session.record_verification(record)

    assert next_session.stage == "VERIFY"
    assert next_session.current_step == "verify-001"
    assert next_session.last_verification == record


def test_start_rejects_replacing_active_task_id() -> None:
    """Once a task is active, switching task identity must go through reset-task."""
    session = TaskSession(
        task_id="old-task",
        workflow_id="research",
        stage="GREEN_IMPL",
        current_step="green-001",
    )

    try:
        session.start("new-task", entry_stage="QUESTIONING", workflow_id="other")
    except RuntimeError as exc:
        assert "reset-task" in str(exc)
    else:
        raise AssertionError("Expected active task replacement to be rejected")


def test_start_rejects_rebinding_active_workflow() -> None:
    """Workflow binding is a task-level fact and cannot change mid-task."""
    session = TaskSession(
        task_id="market-scan",
        workflow_id="research",
        stage="QUESTIONING",
        current_step="question-001",
    )

    try:
        session.start("market-scan", entry_stage="QUESTIONING", workflow_id="coding")
    except RuntimeError as exc:
        assert "different workflow" in str(exc)
        assert "reset-task" in str(exc)
    else:
        raise AssertionError("Expected active workflow rebinding to be rejected")
