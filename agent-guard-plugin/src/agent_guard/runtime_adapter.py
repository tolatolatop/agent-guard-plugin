"""Adapters that turn workflow state into runtime-facing reminders."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .fuse_integration import ensure_fuse_protection
from .plan import first_nonterminal_plan_step_name
from .state import load_state
from .task_reset import latest_archive
from .workflow import build_session_prompt_block, get_workflow_context


def get_next_step(root_dir: Path, state: dict[str, Any]) -> str | None:
    # The plan is the single source of truth for workflow steps.
    """Return next step."""
    return first_nonterminal_plan_step_name(root_dir)


def get_session_reminder(root_dir: Path) -> dict[str, Any]:
    """Return session reminder."""
    fuse = ensure_fuse_protection(root_dir)
    state = load_state(root_dir)
    next_step = get_next_step(root_dir, state)
    stage = state.get("stage", "IDLE")
    workflow_id = str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None
    workflow_context = get_workflow_context(root_dir, stage, workflow_id)
    recent_archive = latest_archive(root_dir)
    navigator = workflow_context["session_start_navigator"]
    prompt_block = build_session_prompt_block(
        task_id=state.get("task_id"),
        stage=stage,
        current_step=state.get("current_step"),
        next_step=next_step,
        can_finalize=bool(state.get("can_finalize")),
        workflow_context=workflow_context,
        recent_archive=recent_archive,
    )
    if fuse.get("protection") != "mounted":
        reason = str(fuse.get("reason") or "agent-guard-fuse is not actively mounted.")
        prompt_block = f"{prompt_block}\nFUSE protection: {fuse.get('protection')} ({reason})"

    return {
        "task": state.get("task_id"),
        "stage": stage,
        "current_step": state.get("current_step"),
        "next_required_action": next_step,
        "can_finalize": state.get("can_finalize"),
        "meta_skill": {
            "name": navigator["name"],
            "path": navigator["path"],
            "absolute_path": navigator["absolute_path"],
            "instruction": navigator["instruction"],
        },
        "workflow": workflow_context,
        "fuse": fuse,
        "recent_archive": recent_archive,
        "prompt_block": prompt_block,
        "reminder": (
            f"Task={state.get('task_id') or 'unset'} "
            f"stage={stage} "
            f"step={state.get('current_step') or 'unset'} "
            f"next={next_step or 'none'} "
            f"finalize={state.get('can_finalize')} "
            f"fuse={fuse.get('protection')}"
        ),
    }
