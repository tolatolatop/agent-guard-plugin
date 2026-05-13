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


def load_plan_summary(root_dir: Path) -> dict[str, Any]:
    steps = plan_steps(root_dir)
    if not steps:
        data = load_plan(root_dir)
        if data is None:
            return {"exists": False, "includesReview": False, "step_count": 0}
    return {"exists": True, "includesReview": False, "step_count": len(steps)}
