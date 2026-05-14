"""Helpers for reading and updating .agent/plan.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .domain.models import PlanStep
from .infrastructure.repositories import PlanRepository
from .state import agent_dir


def plan_path(root_dir: Path) -> Path:
    """Plan path."""
    return agent_dir(root_dir) / "plan.yaml"


def load_plan(root_dir: Path) -> dict[str, Any] | None:
    """Load plan."""
    return PlanRepository(root_dir).load_raw()


def plan_steps(root_dir: Path) -> list[dict[str, str]]:
    """Plan steps."""
    return [step.to_legacy_mapping() for step in plan_step_entities(root_dir)]


def plan_step_entities(root_dir: Path) -> list[PlanStep]:
    """Return structured plan step entities."""
    return PlanRepository(root_dir).load_steps()


def nonterminal_plan_steps(root_dir: Path) -> list[dict[str, str]]:
    # Only done/failed are terminal. Every other status keeps the plan open and
    # blocks finalization.
    """Nonterminal plan steps."""
    terminal_statuses = {"done", "failed"}
    return [step.to_legacy_mapping() for step in plan_step_entities(root_dir) if step.status.strip().lower() not in terminal_statuses]


def first_nonterminal_plan_step_name(root_dir: Path) -> str | None:
    """Return the first nonterminal plan step name."""
    pending = nonterminal_plan_steps(root_dir)
    return pending[0]["name"] if pending else None


def update_plan_step_status(root_dir: Path, step_name: str, status: str) -> dict[str, Any]:
    """Update plan step status."""
    return PlanRepository(root_dir).update_step_status(step_name, status)


def load_plan_summary(root_dir: Path) -> dict[str, Any]:
    """Load plan summary."""
    entities = plan_step_entities(root_dir)
    steps = [step.to_legacy_mapping() for step in entities]
    if not steps:
        data = load_plan(root_dir)
        if data is None:
            return {"exists": False, "includesReview": False, "step_count": 0}
    pending = nonterminal_plan_steps(root_dir)
    return {
        "exists": True,
        "includesReview": any(step.stage == "REVIEW" for step in entities),
        "step_count": len(steps),
        "all_steps_terminal": not pending,
    }
