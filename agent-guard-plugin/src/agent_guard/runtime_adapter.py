from __future__ import annotations

from pathlib import Path
from typing import Any

from .plan import first_nonterminal_plan_step_name
from .state import load_state
from .task_reset import latest_archive
from .workflow import build_session_prompt_block, get_workflow_context


def get_next_step(root_dir: Path, state: dict[str, Any]) -> str | None:
    # Prefer the plan as the source of truth; remaining_steps is only a legacy
    # fallback for older state files.
    plan_step = first_nonterminal_plan_step_name(root_dir)
    if plan_step:
        return plan_step
    remaining = state.get("remaining_steps", [])
    return remaining[0] if remaining else None


def get_session_reminder(root_dir: Path) -> dict[str, Any]:
    state = load_state(root_dir)
    next_step = get_next_step(root_dir, state)
    stage = state.get("stage", "IDLE")
    workflow_context = get_workflow_context(root_dir, stage)
    recent_archive = latest_archive(root_dir)
    meta_skill = next(
        (skill for skill in workflow_context["skill_catalog"] if skill.get("id") == "using-workflow"),
        workflow_context["skill_catalog"][0],
    )
    return {
        "task": state.get("task_id"),
        "stage": stage,
        "current_step": state.get("current_step"),
        "allowed_paths": state.get("allowed_paths"),
        "forbidden_paths": state.get("forbidden_paths"),
        "next_required_action": next_step,
        "can_finalize": state.get("can_finalize"),
        "meta_skill": {
            "name": "Using Workflow",
            "path": meta_skill["path"],
            "absolute_path": meta_skill["absolute_path"],
            "instruction": "Consult this navigator first, then load specialist workflow skills on demand.",
        },
        "workflow": workflow_context,
        "recent_archive": recent_archive,
        "prompt_block": build_session_prompt_block(
            task_id=state.get("task_id"),
            stage=stage,
            current_step=state.get("current_step"),
            next_step=next_step,
            allowed_paths=state.get("allowed_paths", []),
            forbidden_paths=state.get("forbidden_paths", []),
            can_finalize=bool(state.get("can_finalize")),
            workflow_context=workflow_context,
            recent_archive=recent_archive,
        ),
        "reminder": (
            f"Task={state.get('task_id') or 'unset'} "
            f"stage={stage} "
            f"step={state.get('current_step') or 'unset'} "
            f"next={next_step or 'none'} "
            f"finalize={state.get('can_finalize')}"
        ),
    }
