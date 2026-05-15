"""Workflow transition commands and guard enforcement."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .domain.models import TaskSession
from .domain.rules import RuleContext, evaluate_rule
from .events import append_event
from .gates import can_finalize
from .jobs import load_jobs
from .plan import plan_step_entities, update_plan_step_status
from .state import AGENT_DIR, load_state, required_artifact_exit_failures, save_state
from .workflow_spec import (
    complete_step_allowed_from_stages,
    stage_entry_conditions,
    stage_exit_conditions,
    stage_intent,
    stage_transitions,
)

STAGE_TRANSITIONS = stage_transitions()


def transition_conditions_for_stage(stage: str) -> dict[str, list[str]]:
    """Transition conditions for stage."""
    return stage_exit_conditions(stage)


def automatic_transitions() -> list[str]:
    """Automatic transitions."""
    return [
        "start-task: IDLE -> CLARIFYING",
        "wizard: initializes directly into the selected starting stage",
        "record-command: failed non-red command -> NEEDS_FAILURE_ANALYSIS",
        "record-command in VERIFY: updates last_verification",
        "reset-task: archives a completed task and starts a new one in CLARIFYING",
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
    if from_stage == "DONE":
        raise RuntimeError("DONE cannot transition anywhere. Use reset-task or next-task to start a new task.")
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
    artifact_failures = required_artifact_exit_failures(root_dir, from_stage)
    if artifact_failures:
        raise RuntimeError(f"Leaving {from_stage} requires {'; '.join(artifact_failures)}")

    session = TaskSession.from_mapping(state)
    context = RuleContext(root_dir, session, command_name=command_name)
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


def _next_state_common(
    state: dict[str, Any],
    to_stage: str,
    current_step: str | None,
    can_finalize_value: bool,
) -> dict[str, Any]:
    """Internal helper for next state common."""
    next_state = dict(state)
    next_state["stage"] = to_stage
    next_state["current_step"] = current_step
    next_state["can_finalize"] = can_finalize_value
    # needs_human is sticky only inside escalation stages; any normal workflow
    # stage clears it so the task can continue under agent control again.
    if state.get("stage") in {"NEEDS_FAILURE_ANALYSIS", "NEEDS_HUMAN"} and to_stage != "NEEDS_HUMAN":
        next_state["needs_human"] = False
    if to_stage == "NEEDS_HUMAN":
        next_state["needs_human"] = True
    elif to_stage != "READY_TO_SUMMARIZE":
        next_state["can_finalize"] = False
    return next_state


def _append_transition_event(
    root_dir: Path,
    command_name: str,
    from_stage: str,
    to_stage: str,
    state: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal helper for append transition event."""
    payload = {
        "hook": "WorkflowTransition",
        "command": command_name,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "current_step": state.get("current_step"),
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
    state = load_state(root_dir)
    _guard_transition(root_dir, state, to_stage, "advance-stage", step_id)

    resolved_step = step_id or state.get("current_step")
    from_stage = str(state.get("stage"))
    next_state = _next_state_common(
        state,
        to_stage,
        str(resolved_step) if resolved_step else None,
        can_finalize_value=False,
    )
    save_state(root_dir, next_state)
    event = _append_transition_event(root_dir, "advance-stage", from_stage, to_stage, next_state, {"step": resolved_step})
    return {
        "goal": stage_intent(to_stage)["goal"],
        "step_goal": _plan_step_goal(root_dir, str(resolved_step) if resolved_step else None),
        "state": next_state,
        "event": event,
    }


def complete_step(
    root_dir: Path,
    step_id: str,
    next_step_id: str | None = None,
) -> dict[str, Any]:
    """Complete step."""
    state = load_state(root_dir)
    current_stage = str(state.get("stage"))
    if current_stage not in set(complete_step_allowed_from_stages()):
        raise RuntimeError(f"complete-step is not allowed from stage {current_stage}.")
    update_plan_step_status(root_dir, step_id, "done")

    next_state = _next_state_common(
        state,
        current_stage,
        next_step_id,
        can_finalize_value=False,
    )
    next_state["completed_steps"] = []
    next_state["remaining_steps"] = []

    save_state(root_dir, next_state)
    event = _append_transition_event(
        root_dir,
        "complete-step",
        current_stage,
        current_stage,
        next_state,
        {"completed_step": step_id, "next_step": next_step_id},
    )
    return {
        "goal": stage_intent(current_stage)["goal"],
        "completed_step_goal": _plan_step_goal(root_dir, step_id),
        "next_step_goal": _plan_step_goal(root_dir, next_step_id),
        "state": next_state,
        "event": event,
    }


def ready_to_summarize(root_dir: Path) -> dict[str, Any]:
    """Move workflow state so it is ready to summarize."""
    state = load_state(root_dir)
    from_stage = str(state.get("stage"))
    _guard_transition(root_dir, state, "READY_TO_SUMMARIZE", "ready-to-summarize", None)
    next_state = _next_state_common(
        state,
        "READY_TO_SUMMARIZE",
        None,
        can_finalize_value=True,
    )
    save_state(root_dir, next_state)
    event = _append_transition_event(root_dir, "ready-to-summarize", from_stage, "READY_TO_SUMMARIZE", next_state)
    return {"state": next_state, "event": event}


def mark_done(root_dir: Path) -> dict[str, Any]:
    """Mark done."""
    state = load_state(root_dir)
    from_stage = str(state.get("stage"))
    _guard_transition(root_dir, state, "DONE", "mark-done", None)
    next_state = _next_state_common(state, "DONE", None, can_finalize_value=True)
    save_state(root_dir, next_state)
    event = _append_transition_event(root_dir, "mark-done", from_stage, "DONE", next_state)
    return {"state": next_state, "event": event}
