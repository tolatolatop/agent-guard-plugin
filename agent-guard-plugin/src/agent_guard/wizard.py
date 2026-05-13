from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

import yaml

from .interactive import confirm_action, prompt_choice, prompt_text
from .plan import plan_path
from .state import ensure_agent_files, save_state

WIZARD_STAGES = ["CLARIFYING", "PLANNING", "RED_TEST", "GREEN_IMPL"]


def slugify_task_id(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "new-task"


def default_paths_for_stage(stage: str) -> tuple[list[str], list[str]]:
    if stage == "RED_TEST":
        return ["tests/**"], ["src/**"]
    if stage == "GREEN_IMPL":
        return ["src/**", "tests/**"], [".github/**", "infra/**"]
    return [], []


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def write_plan_template(
    root_dir: Path,
    task_id: str,
    stage: str,
    step_name: str | None,
    goal: str,
) -> Path:
    step_identifier = step_name or (
        "red-001" if stage == "RED_TEST" else "green-001" if stage == "GREEN_IMPL" else "step-001"
    )
    status = "in_progress" if stage in {"RED_TEST", "GREEN_IMPL", "PLANNING"} else "pending"
    payload: dict[str, Any] = {
        "task_id": task_id,
        "steps": [
            {
                "name": step_identifier,
                "description": goal,
                "status": status,
            }
        ],
    }
    target = plan_path(root_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def run_wizard(root_dir: Path, input_stream: TextIO, output: TextIO) -> dict[str, Any]:
    ensure_agent_files(root_dir)

    suggested_task = slugify_task_id(root_dir.name)
    task_id = slugify_task_id(prompt_text("Task id", input_stream, output, default=suggested_task))
    goal = prompt_text("Task goal", input_stream, output, default=f"Implement {task_id}")
    stage = prompt_choice("Start stage", WIZARD_STAGES, input_stream, output, default="CLARIFYING")
    current_step = prompt_text("Current step id", input_stream, output, default="")
    allowed_default, forbidden_default = default_paths_for_stage(stage)
    allowed_paths = parse_csv(
        prompt_text("Allowed paths (comma-separated)", input_stream, output, default=", ".join(allowed_default))
    )
    forbidden_paths = parse_csv(
        prompt_text("Forbidden paths (comma-separated)", input_stream, output, default=", ".join(forbidden_default))
    )
    create_plan = confirm_action("Create or replace .agent/plan.yaml?", input_stream, output)

    remaining_steps = [current_step] if current_step else []
    state = save_state(
        root_dir,
        {
            "task_id": task_id,
            "stage": stage,
            "current_step": current_step or None,
            "completed_steps": [],
            "remaining_steps": remaining_steps,
            "allowed_paths": allowed_paths,
            "forbidden_paths": forbidden_paths,
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    result: dict[str, Any] = {
        "ok": True,
        "task_id": task_id,
        "goal": goal,
        "state": state,
        "plan_written": None,
    }
    if create_plan:
        plan_file = write_plan_template(root_dir, task_id, stage, current_step or None, goal)
        result["plan_written"] = str(plan_file)
    return result
