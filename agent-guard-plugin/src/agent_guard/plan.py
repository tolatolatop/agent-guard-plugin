from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .state import agent_dir


def plan_path(root_dir: Path) -> Path:
    return agent_dir(root_dir) / "plan.yaml"


def load_plan_summary(root_dir: Path) -> dict[str, Any]:
    file_path = plan_path(root_dir)
    if not file_path.exists():
        return {"exists": False, "includesReview": False}

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"plan.yaml is invalid YAML: {exc}") from exc

    steps = data.get("steps", [])
    includes_review = any(isinstance(step, dict) and step.get("stage") == "REVIEW" for step in steps)
    return {"exists": True, "includesReview": includes_review}
