"""Workflow transition commands and guard enforcement."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .domain.models import TaskSession
from .domain.policies import StageExitPolicyService
from .domain.rules import RuleContext, evaluate_rule
from .events import append_event
from .gates import can_finalize
from .jobs import load_jobs
from .plan import plan_step_entities, update_plan_step_status
from .state import AGENT_DIR, load_task_session, save_task_session
from .workflow_spec import (
    canonical_completion_ready_stage,
    canonical_completion_stage,
    canonical_entry_stage,
    canonical_failure_analysis_stage,
    canonical_verification_stage,
    complete_step_allowed_from_stages,
    stage_entry_conditions,
    stage_exit_conditions,
    stage_exit_rule_conditions,
    stage_intent,
    stage_transitions,
)

STAGE_TRANSITIONS = stage_transitions()


def transition_conditions_for_stage(stage: str) -> dict[str, list[str]]:
    """Transition conditions for stage."""
    return stage_exit_conditions(stage)


def automatic_transitions() -> list[str]:
    """Automatic transitions."""
    analysis_stage = "failure-analysis stage"
    try:
        analysis_stage = canonical_failure_analysis_stage() or analysis_stage
    except RuntimeError:
        pass
    verification_stage = canonical_verification_stage() or "verification stage"
    return [
        f"start-task: IDLE -> {canonical_entry_stage()}",
        "wizard: initializes directly into the selected starting stage",
        f"record-command: failed non-red command -> {analysis_stage}",
        f"record-command in {verification_stage}: updates last_verification",
        f"reset-task: archives a completed task and starts a new one in {canonical_entry_stage()}",
    ]


def _has_active_task(state: dict[str, Any]) -> bool:
    """Internal helper for has active task."""
    return bool(state.get("task_id"))

def _has_running_jobs(root_dir: Path) -> bool:
    """Internal helper for has running jobs."""
    jobs = load_jobs(root_dir)
    return any(job.get("status") == "running" for job in jobs.get("jobs", []))


def _require_direct_transition(from_stage: str, to_stage: str) -> None:
    """Internal helper for require direct transition."""
    if to_stage not in STAGE_TRANSITIONS:
        raise RuntimeError(f"Unknown target stage: {to_stage}")
    completion_stage = canonical_completion_stage()
    if from_stage == completion_stage:
        raise RuntimeError(f"{completion_stage} cannot transition anywhere. Use reset-task or next-task to start a new task.")
    if to_stage not in STAGE_TRANSITIONS.get(from_stage, []):
        raise RuntimeError(f"Illegal transition: {from_stage} -> {to_stage}")


def _guard_transition(
    root_dir: Path,
    state: dict[str, Any],
    to_stage: str,
    command_name: str,
    step_id: str | None,
) -> None:
    """Internal helper for guard transition."""
    from_stage = str(state.get("stage"))
    _require_direct_transition(from_stage, to_stage)
    artifact_failures = StageExitPolicyService(root_dir).exit_failures(from_stage)
    if artifact_failures:
        raise RuntimeError(f"Leaving {from_stage} requires {'; '.join(artifact_failures)}")

    session = TaskSession.from_mapping(state)
    context = RuleContext(root_dir, session, command_name=command_name)
    for condition in stage_exit_rule_conditions(from_stage):
        display = condition["display"]
        rule = condition.get("rule")
        if rule is None:
            continue
        if not evaluate_rule(rule, context, condition.get("value")):
            raise RuntimeError(display)
    for condition in stage_entry_conditions(to_stage, from_stage):
        display = condition["display"]
        rule = condition.get("rule")
        if rule is None:
            continue
        if not evaluate_rule(rule, context, condition.get("value")):
            if rule == "can_finalize_passes":
                result = can_finalize(root_dir)
                reasons = "; ".join(str(reason) for reason in result.get("reasons", []))
                raise RuntimeError(f"{display}: {reasons}" if reasons else display)
            raise RuntimeError(display)


def _append_transition_event(
    root_dir: Path,
    command_name: str,
    from_stage: str,
    to_stage: str,
    session: TaskSession,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal helper for append transition event."""
    payload = {
        "hook": "WorkflowTransition",
        "command": command_name,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "current_step": session.current_step,
    }
    if extra:
        payload.update(extra)
    return append_event(root_dir, payload)


def _plan_step_goal(root_dir: Path, step_id: str | None) -> str | None:
    """Return one plan step goal when the step exists."""
    if not step_id:
        return None
    for step in plan_step_entities(root_dir):
        if step.id == step_id:
            return step.goal
    return None


def advance_stage(
    root_dir: Path,
    to_stage: str,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Advance stage."""
    session = load_task_session(root_dir)
    _guard_transition(root_dir, session.to_mapping(), to_stage, "advance-stage", step_id)

    resolved_step = step_id or session.current_step
    from_stage = session.stage
    next_session = session.advance_to(
        to_stage,
        current_step=str(resolved_step) if resolved_step else None,
        can_finalize=False,
    )
    save_task_session(root_dir, next_session)
    event = _append_transition_event(root_dir, "advance-stage", from_stage, to_stage, next_session, {"step": resolved_step})
    return {
        "goal": stage_intent(to_stage)["goal"],
        "step_goal": _plan_step_goal(root_dir, str(resolved_step) if resolved_step else None),
        "state": next_session.to_mapping(),
        "event": event,
    }


def complete_step(
    root_dir: Path,
    step_id: str,
    next_step_id: str | None = None,
) -> dict[str, Any]:
    """Complete step."""
    session = load_task_session(root_dir)
    current_stage = session.stage
    if current_stage not in set(complete_step_allowed_from_stages()):
        raise RuntimeError(f"complete-step is not allowed from stage {current_stage}.")
    update_plan_step_status(root_dir, step_id, "done")

    next_session = session.advance_to(
        current_stage,
        current_step=next_step_id,
        can_finalize=False,
    )
    save_task_session(root_dir, next_session)
    event = _append_transition_event(
        root_dir,
        "complete-step",
        current_stage,
        current_stage,
        next_session,
        {"completed_step": step_id, "next_step": next_step_id},
    )
    return {
        "goal": stage_intent(current_stage)["goal"],
        "completed_step_goal": _plan_step_goal(root_dir, step_id),
        "next_step_goal": _plan_step_goal(root_dir, next_step_id),
        "state": next_session.to_mapping(),
        "event": event,
    }


def ready_to_summarize(root_dir: Path) -> dict[str, Any]:
    """Move workflow state so it is ready to summarize."""
    session = load_task_session(root_dir)
    from_stage = session.stage
    target_stage = canonical_completion_ready_stage()
    _guard_transition(root_dir, session.to_mapping(), target_stage, "ready-to-summarize", None)
    next_session = session.mark_ready_to_summarize(target_stage)
    save_task_session(root_dir, next_session)
    event = _append_transition_event(root_dir, "ready-to-summarize", from_stage, target_stage, next_session)
    return {"state": next_session.to_mapping(), "event": event}


def mark_done(root_dir: Path) -> dict[str, Any]:
    """Mark done."""
    session = load_task_session(root_dir)
    from_stage = session.stage
    target_stage = canonical_completion_stage()
    _guard_transition(root_dir, session.to_mapping(), target_stage, "mark-done", None)
    next_session = session.mark_done(target_stage)
    save_task_session(root_dir, next_session)
    event = _append_transition_event(root_dir, "mark-done", from_stage, target_stage, next_session)
    return {"state": next_session.to_mapping(), "event": event}
