from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import append_event
from .gates import can_finalize
from .jobs import load_jobs
from .plan import get_plan_step, load_plan_summary
from .state import AGENT_DIR, load_state, save_state

STAGE_TRANSITIONS = {
    "IDLE": ["CLARIFYING"],
    "CLARIFYING": ["DESIGNING", "PLANNING"],
    "DESIGNING": ["PLANNING"],
    "PLANNING": ["RED_TEST", "GREEN_IMPL"],
    "RED_TEST": ["GREEN_IMPL", "NEEDS_FAILURE_ANALYSIS"],
    "GREEN_IMPL": ["REVIEW", "NEEDS_FAILURE_ANALYSIS"],
    "REVIEW": ["VERIFY", "GREEN_IMPL"],
    "VERIFY": ["READY_TO_SUMMARIZE", "NEEDS_FAILURE_ANALYSIS"],
    "READY_TO_SUMMARIZE": ["DONE"],
    "NEEDS_FAILURE_ANALYSIS": ["RED_TEST", "GREEN_IMPL", "VERIFY", "NEEDS_HUMAN"],
    "NEEDS_HUMAN": ["CLARIFYING", "PLANNING"],
    "DONE": [],
}

TRANSITION_CONDITIONS = {
    "IDLE": {
        "CLARIFYING": ["task_id must be set"],
    },
    "CLARIFYING": {
        "DESIGNING": ["active task exists", "needs_human must be false"],
        "PLANNING": ["active task exists", "caller has clarified requirements"],
    },
    "DESIGNING": {
        "PLANNING": ["active task exists"],
    },
    "PLANNING": {
        "RED_TEST": ["step must be selected", "scope must be known from plan or explicit flags"],
        "GREEN_IMPL": ["step must be selected", "scope must be known from plan or explicit flags"],
    },
    "RED_TEST": {
        "GREEN_IMPL": ["current red step must be completed with complete-step"],
        "NEEDS_FAILURE_ANALYSIS": ["unexpected failure requires analysis"],
    },
    "GREEN_IMPL": {
        "REVIEW": ["current impl step must be completed"],
        "NEEDS_FAILURE_ANALYSIS": ["unexpected failure requires analysis"],
    },
    "REVIEW": {
        "VERIFY": ["review artifact required when plan includes review"],
        "GREEN_IMPL": ["review identified follow-up implementation work"],
    },
    "VERIFY": {
        "READY_TO_SUMMARIZE": ["last_verification.exit_code must be 0", "no running jobs", "remaining steps must be complete", "can_finalize enabled only through ready-to-summarize"],
        "NEEDS_FAILURE_ANALYSIS": ["verification failed"],
    },
    "READY_TO_SUMMARIZE": {
        "DONE": ["can-finalize must pass", "use mark-done"],
    },
    "NEEDS_FAILURE_ANALYSIS": {
        "RED_TEST": ["failure-analysis.md must exist", "next step and scope must be known"],
        "GREEN_IMPL": ["failure-analysis.md must exist", "next step and scope must be known"],
        "VERIFY": ["failure-analysis.md must exist"],
        "NEEDS_HUMAN": ["explicit escalation"],
    },
    "NEEDS_HUMAN": {
        "CLARIFYING": ["human guidance received"],
        "PLANNING": ["human guidance resolved scope and next step"],
    },
    "DONE": {},
}


def parse_scope_flag(value: str | bool | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def transition_conditions_for_stage(stage: str) -> dict[str, list[str]]:
    return TRANSITION_CONDITIONS.get(stage, {})


def transition_graph_lines() -> list[str]:
    return [
        "IDLE -> CLARIFYING",
        "CLARIFYING -> DESIGNING | PLANNING",
        "DESIGNING -> PLANNING",
        "PLANNING -> RED_TEST | GREEN_IMPL",
        "RED_TEST -> GREEN_IMPL | NEEDS_FAILURE_ANALYSIS",
        "GREEN_IMPL -> REVIEW | NEEDS_FAILURE_ANALYSIS",
        "REVIEW -> VERIFY | GREEN_IMPL",
        "VERIFY -> READY_TO_SUMMARIZE | NEEDS_FAILURE_ANALYSIS",
        "READY_TO_SUMMARIZE -> DONE",
        "NEEDS_FAILURE_ANALYSIS -> RED_TEST | GREEN_IMPL | VERIFY | NEEDS_HUMAN",
        "NEEDS_HUMAN -> CLARIFYING | PLANNING",
        "DONE -> reset-task / next-task only",
    ]


def workflow_commands() -> list[str]:
    return [
        "agent-guard advance-stage --to <stage> [--step <step-id>] [--allowed-paths <csv>] [--forbidden-paths <csv>]",
        "agent-guard complete-step <step-id> --next-stage <stage> [--next-step <step-id>] [--allowed-paths <csv>] [--forbidden-paths <csv>]",
        "agent-guard ready-to-summarize",
        "agent-guard mark-done",
    ]


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
    return (root_dir / AGENT_DIR / "artifacts" / "review.json").exists()


def _failure_analysis_exists(root_dir: Path) -> bool:
    return (root_dir / AGENT_DIR / "artifacts" / "failure-analysis.md").exists()


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
    root_dir: Path,
    step_id: str | None,
    explicit_allowed_paths: list[str],
    explicit_forbidden_paths: list[str],
    require_scope: bool,
) -> tuple[list[str], list[str], dict[str, Any] | None]:
    if step_id:
        step = get_plan_step(root_dir, step_id)
        if step is not None:
            allowed = list(step.get("allowed_paths", []))
            forbidden = list(step.get("forbidden_paths", []))
            if require_scope and not allowed:
                raise RuntimeError(f"Plan step {step_id} must define allowed_paths before entering an execution stage.")
            return allowed, forbidden, step

    if require_scope and not explicit_allowed_paths:
        raise RuntimeError("Step scope is required. Add the step to .agent/plan.yaml or pass --allowed-paths.")
    if explicit_allowed_paths or explicit_forbidden_paths:
        return list(explicit_allowed_paths), list(explicit_forbidden_paths), None
    return [], [], None


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

    if to_stage == "READY_TO_SUMMARIZE" and command_name != "ready-to-summarize":
        raise RuntimeError("Use agent-guard ready-to-summarize after verification succeeds.")
    if to_stage == "DONE" and command_name != "mark-done":
        raise RuntimeError("Use agent-guard mark-done to enter DONE.")

    if from_stage == "IDLE" and to_stage == "CLARIFYING" and not _has_active_task(state):
        raise RuntimeError("IDLE -> CLARIFYING requires task_id to be set first.")

    if from_stage == "CLARIFYING":
        if not _has_active_task(state):
            raise RuntimeError("Current task is unset. Run start-task or wizard first.")
        if to_stage == "DESIGNING" and state.get("needs_human") is True:
            raise RuntimeError("Cannot enter DESIGNING while needs_human is true.")

    if from_stage == "DESIGNING" and not _has_active_task(state):
        raise RuntimeError("DESIGNING -> PLANNING requires an active task.")

    if from_stage == "PLANNING" and to_stage in {"RED_TEST", "GREEN_IMPL"}:
        selected_step = step_id or state.get("current_step")
        if not selected_step:
            raise RuntimeError(f"{from_stage} -> {to_stage} requires a step. Pass --step or set current_step first.")
        _resolve_scope(root_dir, str(selected_step), allowed_paths, forbidden_paths, require_scope=True)

    if from_stage == "RED_TEST" and to_stage == "GREEN_IMPL" and command_name == "advance-stage":
        raise RuntimeError("RED_TEST -> GREEN_IMPL requires complete-step so the red step is recorded as complete.")

    if from_stage == "GREEN_IMPL" and to_stage in {"REVIEW", "VERIFY"} and command_name == "advance-stage":
        if not _step_already_completed(state):
            raise RuntimeError(f"{from_stage} -> {to_stage} requires complete-step for the current implementation step.")

    if from_stage == "REVIEW" and to_stage == "VERIFY":
        if load_plan_summary(root_dir).get("includesReview") and not _review_artifact_exists(root_dir):
            raise RuntimeError("REVIEW -> VERIFY requires .agent/artifacts/review.json when the plan includes review.")

    if from_stage == "VERIFY" and to_stage == "READY_TO_SUMMARIZE":
        last_verification = state.get("last_verification")
        if not last_verification or last_verification.get("exit_code") != 0:
            raise RuntimeError("VERIFY -> READY_TO_SUMMARIZE requires a successful last_verification.")
        if _has_running_jobs(root_dir):
            raise RuntimeError("VERIFY -> READY_TO_SUMMARIZE is blocked while jobs are still running.")
        if state.get("remaining_steps"):
            raise RuntimeError("VERIFY -> READY_TO_SUMMARIZE requires remaining_steps to be empty.")

    if from_stage == "READY_TO_SUMMARIZE" and to_stage == "DONE":
        result = can_finalize(root_dir)
        if result["decision"] != "allow":
            reasons = "; ".join(str(reason) for reason in result.get("reasons", []))
            raise RuntimeError(f"READY_TO_SUMMARIZE -> DONE is blocked: {reasons}")

    if from_stage == "NEEDS_FAILURE_ANALYSIS" and to_stage != "NEEDS_HUMAN":
        if not _failure_analysis_exists(root_dir):
            raise RuntimeError(
                "Leaving NEEDS_FAILURE_ANALYSIS requires .agent/artifacts/failure-analysis.md."
            )
        if to_stage in {"RED_TEST", "GREEN_IMPL"}:
            selected_step = step_id or state.get("current_step")
            if not selected_step:
                raise RuntimeError(f"{from_stage} -> {to_stage} requires a next step. Pass --step or set current_step first.")
            _resolve_scope(root_dir, str(selected_step), allowed_paths, forbidden_paths, require_scope=True)


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
    if step_id:
        require_scope = to_stage in {"RED_TEST", "GREEN_IMPL"}
        resolved_allowed, resolved_forbidden, _ = _resolve_scope(root_dir, step_id, allowed, forbidden, require_scope)
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
    if current_stage not in {"RED_TEST", "GREEN_IMPL", "REVIEW", "VERIFY"}:
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
        resolved_allowed, resolved_forbidden, _ = _resolve_scope(
            root_dir,
            resolved_next_step,
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
