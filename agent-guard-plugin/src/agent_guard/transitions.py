from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import append_event
from .gates import can_finalize
from .jobs import load_jobs
from .state import AGENT_DIR, load_state, save_state
from .workflow_spec import (
    complete_step_allowed_from_stages,
    stage_exit_conditions,
    stage_required_artifacts,
    stage_transition_rules,
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


def _review_artifact_exists(root_dir: Path) -> bool:
    required = stage_required_artifacts("REVIEW")
    return all((root_dir / path).exists() for path in required)


def _failure_analysis_exists(root_dir: Path) -> bool:
    required = stage_required_artifacts("NEEDS_FAILURE_ANALYSIS")
    return all((root_dir / path).exists() for path in required)


def _required_artifacts_message(stage: str) -> str:
    required = stage_required_artifacts(stage)
    if not required:
        return f"{stage} has no required artifacts."
    if len(required) == 1:
        return required[0]
    return ", ".join(required)


def _required_command_message(required_command: str, to_stage: str) -> str:
    if required_command == "ready-to-summarize":
        return "Use agent-guard ready-to-summarize after verification succeeds."
    if required_command == "mark-done":
        return "Use agent-guard mark-done to enter DONE."
    return f"Use agent-guard {required_command} to enter {to_stage}."


def _has_running_jobs(root_dir: Path) -> bool:
    jobs = load_jobs(root_dir)
    return any(job.get("status") == "running" for job in jobs.get("jobs", []))


def _step_already_completed(state: dict[str, Any]) -> bool:
    current_step = state.get("current_step")
    if not current_step:
        return True
    return current_step in state.get("completed_steps", [])


def _require_direct_transition(from_stage: str, to_stage: str) -> None:
    if to_stage not in STAGE_TRANSITIONS:
        raise RuntimeError(f"Unknown target stage: {to_stage}")
    if from_stage == "DONE":
        raise RuntimeError("DONE cannot transition anywhere. Use reset-task or next-task to start a new task.")
    if to_stage not in STAGE_TRANSITIONS.get(from_stage, []):
        raise RuntimeError(f"Illegal transition: {from_stage} -> {to_stage}")


def _resolve_scope(
    current_allowed_paths: list[str],
    current_forbidden_paths: list[str],
    explicit_allowed_paths: list[str],
    explicit_forbidden_paths: list[str],
    require_scope: bool,
) -> tuple[list[str], list[str]]:
    if explicit_allowed_paths or explicit_forbidden_paths:
        return list(explicit_allowed_paths), list(explicit_forbidden_paths)
    if require_scope and not current_allowed_paths:
        raise RuntimeError("Step scope is required. Pass --allowed-paths.")
    return list(current_allowed_paths), list(current_forbidden_paths)


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
    rule = stage_transition_rules(from_stage).get(to_stage, {})
    required_command = rule.get("required_command")
    if required_command and command_name != required_command:
        raise RuntimeError(_required_command_message(str(required_command), to_stage))

    if rule.get("require_active_task") is True and not _has_active_task(state):
        if from_stage == "IDLE":
            raise RuntimeError("IDLE -> CLARIFYING requires task_id to be set first.")
        raise RuntimeError("Current task is unset. Run start-task or wizard first.")

    if rule.get("forbid_needs_human") is True and state.get("needs_human") is True:
        raise RuntimeError(f"Cannot enter {to_stage} while needs_human is true.")

    selected_step = step_id or state.get("current_step")
    require_selected_step = rule.get("require_selected_step") is True
    require_scope = rule.get("require_scope") is True
    if require_selected_step and not selected_step:
        noun = "next step" if from_stage == "NEEDS_FAILURE_ANALYSIS" else "step"
        raise RuntimeError(f"{from_stage} -> {to_stage} requires a {noun}. Pass --step or set current_step first.")
    if (require_selected_step or require_scope) and selected_step:
        _resolve_scope(
            list(state.get("allowed_paths", [])),
            list(state.get("forbidden_paths", [])),
            allowed_paths,
            forbidden_paths,
            require_scope=require_scope,
        )

    required_completion_commands = {
        str(item) for item in rule.get("require_completed_current_step_on_commands", []) if str(item)
    }
    if command_name in required_completion_commands and not _step_already_completed(state):
        raise RuntimeError(f"{from_stage} -> {to_stage} requires complete-step for the current implementation step.")

    if rule.get("require_review_artifacts") is True and not _review_artifact_exists(root_dir):
        raise RuntimeError(f"REVIEW -> VERIFY requires {_required_artifacts_message('REVIEW')}.")

    if rule.get("require_successful_last_verification") is True:
        last_verification = state.get("last_verification")
        if not last_verification or last_verification.get("exit_code") != 0:
            raise RuntimeError("VERIFY -> READY_TO_SUMMARIZE requires a successful last_verification.")

    if rule.get("require_no_running_jobs") is True and _has_running_jobs(root_dir):
        raise RuntimeError("VERIFY -> READY_TO_SUMMARIZE is blocked while jobs are still running.")

    if rule.get("require_empty_remaining_steps") is True and state.get("remaining_steps"):
        raise RuntimeError("VERIFY -> READY_TO_SUMMARIZE requires remaining_steps to be empty.")

    if rule.get("require_can_finalize") is True:
        result = can_finalize(root_dir)
        if result["decision"] != "allow":
            reasons = "; ".join(str(reason) for reason in result.get("reasons", []))
            raise RuntimeError(f"READY_TO_SUMMARIZE -> DONE is blocked: {reasons}")

    if rule.get("require_failure_analysis_artifacts") is True and not _failure_analysis_exists(root_dir):
        raise RuntimeError(
            f"Leaving NEEDS_FAILURE_ANALYSIS requires {_required_artifacts_message('NEEDS_FAILURE_ANALYSIS')}."
        )


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
    resolved_allowed = allowed
    resolved_forbidden = forbidden
    if to_stage in {"RED_TEST", "GREEN_IMPL"}:
        same_step = step_id is None or str(step_id) == str(state.get("current_step") or "")
        fallback_allowed = list(state.get("allowed_paths", [])) if same_step else []
        fallback_forbidden = list(state.get("forbidden_paths", [])) if same_step else []
        resolved_allowed, resolved_forbidden = _resolve_scope(
            fallback_allowed,
            fallback_forbidden,
            allowed,
            forbidden,
            require_scope=True,
        )
    elif to_stage not in {"RED_TEST", "GREEN_IMPL"}:
        resolved_allowed = []
        resolved_forbidden = []

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
    if step_id not in state.get("remaining_steps", []) and step_id != state.get("current_step"):
        raise RuntimeError(f"Step {step_id} is not the active remaining step.")

    completed_steps = [item for item in state.get("completed_steps", []) if item != step_id] + [step_id]
    remaining_steps = [item for item in state.get("remaining_steps", []) if item != step_id]
    resolved_next_step = next_step_id or (remaining_steps[0] if remaining_steps else None)
    allowed = list(allowed_paths or [])
    forbidden = list(forbidden_paths or [])

    _guard_transition(root_dir, state, next_stage, "complete-step", resolved_next_step, allowed, forbidden)

    resolved_allowed: list[str] = []
    resolved_forbidden: list[str] = []
    if resolved_next_step:
        require_scope = next_stage in {"RED_TEST", "GREEN_IMPL"}
        same_step = str(resolved_next_step) == str(state.get("current_step") or "")
        fallback_allowed = list(state.get("allowed_paths", [])) if same_step else []
        fallback_forbidden = list(state.get("forbidden_paths", [])) if same_step else []
        resolved_allowed, resolved_forbidden = _resolve_scope(
            fallback_allowed,
            fallback_forbidden,
            allowed,
            forbidden,
            require_scope,
        )
    elif next_stage in {"RED_TEST", "GREEN_IMPL"}:
        raise RuntimeError(f"Entering {next_stage} requires --next-step or a remaining planned step.")

    next_state = _next_state_common(
        state,
        next_stage,
        resolved_next_step,
        resolved_allowed,
        resolved_forbidden,
        can_finalize_value=next_stage == "READY_TO_SUMMARIZE",
    )
    next_state["completed_steps"] = completed_steps
    next_state["remaining_steps"] = remaining_steps

    save_state(root_dir, next_state)
    event = _append_transition_event(
        root_dir,
        "complete-step",
        current_stage,
        next_stage,
        next_state,
        {"completed_step": step_id, "next_step": resolved_next_step},
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
