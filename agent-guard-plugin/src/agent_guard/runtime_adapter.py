from __future__ import annotations

from pathlib import Path
from typing import Any

from .state import load_state


def get_next_step(state: dict[str, Any]) -> str | None:
    remaining = state.get("remaining_steps", [])
    return remaining[0] if remaining else None


def get_session_reminder(root_dir: Path) -> dict[str, Any]:
    state = load_state(root_dir)
    next_step = get_next_step(state)
    return {
        "task": state.get("task_id"),
        "stage": state.get("stage"),
        "current_step": state.get("current_step"),
        "allowed_paths": state.get("allowed_paths"),
        "forbidden_paths": state.get("forbidden_paths"),
        "next_required_action": next_step,
        "can_finalize": state.get("can_finalize"),
        "reminder": (
            f"Task={state.get('task_id') or 'unset'} "
            f"stage={state.get('stage')} "
            f"step={state.get('current_step') or 'unset'} "
            f"next={next_step or 'none'} "
            f"finalize={state.get('can_finalize')}"
        ),
    }
