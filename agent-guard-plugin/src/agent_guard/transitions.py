from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import append_event
from .gates import can_finalize
from .jobs import load_jobs
from .plan import nonterminal_plan_steps, update_plan_step_status
from .state import AGENT_DIR, load_state, save_state
from .workflow_spec import (
    complete_step_allowed_from_stages,
    stage_entry_conditions,
    stage_exit_conditions,
    stage_required_artifacts,
    stage_transitions,
)

STAGE_TRANSITIONS = stage_transitions()


def parse_scope_flag(value: str | bool | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def transition_conditions_for_stage(stage: str) -> dict[str, list[str]]:
    return stage_exit_conditions(stage)


def automatic_transitions() -> list[str]:
    return [
        "start-task: IDLE -> CLARIFYING",
        "wizard: initializes directly into the selected starting stage",
        "record-command: failed non-red command -> NEEDS_FAILURE_ANALYSIS",
        "record-command in VERIFY: updates last_verification",
        "reset-task: archives a completed task and starts a new one in CLARIFYING",
    ]


def _has_active_task(state: dict[str, Any]) -> bool:
    return bool(state.get("task_id"))

def _required_artifacts_message(stage: str) -> str:
    required = stage_required_artifacts(stage)
    if not required:
        return f"{stage} has no required artifacts."
    if len(required) == 1:
        return required[0]
    return ", ".join(required)


def _has_running_jobs(root_dir: Path) -> bool:
    jobs = load_jobs(root_dir)
    return any(job.get("status") == "running" for job in jobs.get("jobs", []))


def _require_direct_transition(from_stage: str, to_stage: str) -> None:
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
    allowed_paths: list[str],
    forbidden_paths: list[str],
) -> None:
    from_stage = str(state.get("stage"))
    _require_direct_transition(from_stage, to_stage)
    current_required = stage_required_artifacts(from_stage)
    if current_required and not all((root_dir / path).exists() for path in current_required):
        raise RuntimeError(f"Leaving {from_stage} requires {_required_artifacts_message(from_stage)}.")

    for condition in stage_entry_conditions(to_stage, from_stage):
        display = condition["display"]
        rule = condition.get("rule")
        if rule == "required_command":
            required_command = condition.get("value", "")
            if command_name != required_command:
                raise RuntimeError(display)
        elif rule == "active_task":
            if not _has_active_task(state):
                raise RuntimeError(display)
        elif rule == "successful_last_verification":
            last_verification = state.get("last_verification")
            if not last_verification or last_verification.get("exit_code") != 0:
                raise RuntimeError(display)
        elif rule == "no_running_jobs":
            if _has_running_jobs(root_dir):
                raise RuntimeError(display)
        elif rule == "all_plan_steps_terminal":
            if nonterminal_plan_steps(root_dir):
                raise RuntimeError(display)
        elif rule == "can_finalize_passes":
            result = can_finalize(root_dir)
            if result["decision"] != "allow":
                reasons = "; ".join(str(reason) for reason in result.get("reasons", []))
                raise RuntimeError(f"{display}: {reasons}" if reasons else display)
        elif rule is None:
            continue
        else:
            raise RuntimeError(f"Unknown entry condition rule for {to_stage}: {rule}")


def _next_state_common(
    state: dict[str, Any],
    to_stage: str,
    current_step: str | None,
    allowed_paths: list[str],
    forbidden_paths: list[str],
    can_finalize_value: bool,
) -> dict[str, Any]:
    next_state = dict(state)
    next_state["stage"] = to_stage
    next_state["current_step"] = current_step
    next_state["allowed_paths"] = allowed_paths
    next_state["forbidden_paths"] = forbidden_paths
    next_state["can_finalize"] = can_finalize_value
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


def advance_stage(
    root_dir: Path,
    to_stage: str,
    step_id: str | None = None,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
) -> dict[str, Any]:
    state = load_state(root_dir)
    allowed = list(allowed_paths or [])
    forbidden = list(forbidden_paths or [])
    _guard_transition(root_dir, state, to_stage, "advance-stage", step_id, allowed, forbidden)

    resolved_step = step_id or state.get("current_step")
    resolved_allowed = list(allowed or state.get("allowed_paths", [])) if to_stage in {"RED_TEST", "GREEN_IMPL"} else []
    resolved_forbidden = list(forbidden or state.get("forbidden_paths", [])) if to_stage in {"RED_TEST", "GREEN_IMPL"} else []

    from_stage = str(state.get("stage"))
    next_state = _next_state_common(
        state,
        to_stage,
        str(resolved_step) if resolved_step else None,
        resolved_allowed,
        resolved_forbidden,
        can_finalize_value=False,
    )
    save_state(root_dir, next_state)
    event = _append_transition_event(root_dir, "advance-stage", from_stage, to_stage, next_state, {"step": resolved_step})
    return {"state": next_state, "event": event}


def complete_step(
    root_dir: Path,
    step_id: str,
    next_stage: str,
    next_step_id: str | None = None,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
) -> dict[str, Any]:
    state = load_state(root_dir)
    current_stage = str(state.get("stage"))
    if current_stage not in set(complete_step_allowed_from_stages()):
        raise RuntimeError(f"complete-step is not allowed from stage {current_stage}.")
    allowed = list(allowed_paths or [])
    forbidden = list(forbidden_paths or [])

    _guard_transition(root_dir, state, next_stage, "complete-step", None, allowed, forbidden)
    update_plan_step_status(root_dir, step_id, "done")

    resolved_allowed = list(allowed or state.get("allowed_paths", [])) if next_stage in {"RED_TEST", "GREEN_IMPL"} else []
    resolved_forbidden = list(forbidden or state.get("forbidden_paths", [])) if next_stage in {"RED_TEST", "GREEN_IMPL"} else []

    next_state = _next_state_common(
        state,
        next_stage,
        None,
        resolved_allowed,
        resolved_forbidden,
        can_finalize_value=next_stage == "READY_TO_SUMMARIZE",
    )
    next_state["current_step"] = None
    next_state["completed_steps"] = []
    next_state["remaining_steps"] = []

    save_state(root_dir, next_state)
    event = _append_transition_event(
        root_dir,
        "complete-step",
        current_stage,
        next_stage,
        next_state,
        {"completed_step": step_id, "next_step": next_step_id},
    )
    return {"state": next_state, "event": event}


def ready_to_summarize(root_dir: Path) -> dict[str, Any]:
    state = load_state(root_dir)
    from_stage = str(state.get("stage"))
    _guard_transition(root_dir, state, "READY_TO_SUMMARIZE", "ready-to-summarize", None, [], [])
    next_state = _next_state_common(
        state,
        "READY_TO_SUMMARIZE",
        None,
        [],
        [],
        can_finalize_value=True,
    )
    save_state(root_dir, next_state)
    event = _append_transition_event(root_dir, "ready-to-summarize", from_stage, "READY_TO_SUMMARIZE", next_state)
    return {"state": next_state, "event": event}


def mark_done(root_dir: Path) -> dict[str, Any]:
    state = load_state(root_dir)
    from_stage = str(state.get("stage"))
    _guard_transition(root_dir, state, "DONE", "mark-done", None, [], [])
    next_state = _next_state_common(state, "DONE", None, [], [], can_finalize_value=True)
    save_state(root_dir, next_state)
    event = _append_transition_event(root_dir, "mark-done", from_stage, "DONE", next_state)
    return {"state": next_state, "event": event}
