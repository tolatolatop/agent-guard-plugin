from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .state import agent_dir


def plan_path(root_dir: Path) -> Path:
    return agent_dir(root_dir) / "plan.yaml"


def load_plan(root_dir: Path) -> dict[str, Any] | None:
    file_path = plan_path(root_dir)
    if not file_path.exists():
        return None

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"plan.yaml is invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("plan.yaml must contain a YAML mapping.")
    steps = data.get("steps", [])
    if steps is None:
        data["steps"] = []
    elif not isinstance(steps, list):
        raise RuntimeError("plan.yaml steps must be a list.")
    return data


def _normalize_step(step: Any, index: int) -> dict[str, str]:
    if not isinstance(step, dict):
        raise RuntimeError(f"plan.yaml step at index {index} must be a mapping.")

    normalized: dict[str, str] = {}
    for field_name in ("name", "description", "status"):
        value = step.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"plan.yaml step at index {index} field {field_name} must be a non-empty string.")
        normalized[field_name] = value
    return normalized


def plan_steps(root_dir: Path) -> list[dict[str, str]]:
    data = load_plan(root_dir)
    if data is None:
        return []
    return [_normalize_step(step, index) for index, step in enumerate(data.get("steps", []))]


def nonterminal_plan_steps(root_dir: Path) -> list[dict[str, str]]:
    # Only done/failed are terminal. Every other status keeps the plan open and
    # blocks finalization.
    terminal_statuses = {"done", "failed"}
    return [
        step for step in plan_steps(root_dir) if step.get("status", "").strip().lower() not in terminal_statuses
    ]


def first_nonterminal_plan_step_name(root_dir: Path) -> str | None:
    pending = nonterminal_plan_steps(root_dir)
    return pending[0]["name"] if pending else None


def update_plan_step_status(root_dir: Path, step_name: str, status: str) -> dict[str, Any]:
    data = load_plan(root_dir)
    if data is None:
        raise RuntimeError("plan.yaml does not exist.")

    steps = data.get("steps", [])
    updated = False
    for index, step in enumerate(steps):
        normalized = _normalize_step(step, index)
        if normalized["name"] != step_name:
            continue
        # Match by stable step name so workflow commands do not depend on
        # transient state.current_step tracking.
        step["status"] = status
        updated = True
        break

    if not updated:
        raise RuntimeError(f"plan.yaml step {step_name} was not found.")

    plan_path(root_dir).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return data


def load_plan_summary(root_dir: Path) -> dict[str, Any]:
    steps = plan_steps(root_dir)
    if not steps:
        data = load_plan(root_dir)
        if data is None:
            return {"exists": False, "includesReview": False, "step_count": 0}
    pending = nonterminal_plan_steps(root_dir)
    return {
        "exists": True,
        "includesReview": False,
        "step_count": len(steps),
        "all_steps_terminal": not pending,
    }
