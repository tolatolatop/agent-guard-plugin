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


def _normalize_path_list(raw: Any, field_name: str, step_id: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RuntimeError(f"plan.yaml step {step_id} field {field_name} must be a list of strings.")
    return list(raw)


def get_plan_step(root_dir: Path, step_id: str) -> dict[str, Any] | None:
    data = load_plan(root_dir)
    if data is None:
        return None

    for step in data.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("id") != step_id:
            continue
        stage = step.get("stage")
        if stage is not None and not isinstance(stage, str):
            raise RuntimeError(f"plan.yaml step {step_id} field stage must be a string.")
        return {
            **step,
            "allowed_paths": _normalize_path_list(step.get("allowed_paths"), "allowed_paths", step_id),
            "forbidden_paths": _normalize_path_list(step.get("forbidden_paths"), "forbidden_paths", step_id),
        }
    return None


def load_plan_summary(root_dir: Path) -> dict[str, Any]:
    data = load_plan(root_dir)
    if data is None:
        return {"exists": False, "includesReview": False}

    steps = data.get("steps", [])
    includes_review = any(isinstance(step, dict) and step.get("stage") == "REVIEW" for step in steps)
    return {"exists": True, "includesReview": includes_review}
