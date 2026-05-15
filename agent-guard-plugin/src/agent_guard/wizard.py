"""Interactive wizard helpers for initializing workflow state."""
from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from .application.use_cases import plan_template_step
from .interactive import confirm_action, prompt_choice, prompt_text
from .infrastructure.repositories import PlanRepository
from .state import ensure_agent_files, save_state
from .workflow_spec import wizard_defaults

WIZARD_STAGES = wizard_defaults()["start_stages"]


def slugify_task_id(value: str) -> str:
    """Slugify task id."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "new-task"


def write_plan_template(
    root_dir: Path,
    task_id: str,
    stage: str,
    step_name: str | None,
    goal: str,
) -> Path:
    """Write plan template."""
    repository = PlanRepository(root_dir)
    repository.save_steps(task_id, [plan_template_step(task_id, stage, step_name, goal)])
    return repository.file_path


def run_wizard(root_dir: Path, input_stream: TextIO, output: TextIO) -> dict[str, Any]:
    """Run wizard."""
    ensure_agent_files(root_dir)

    suggested_task = slugify_task_id(root_dir.name)
    task_id = slugify_task_id(prompt_text("Task id", input_stream, output, default=suggested_task))
    goal = prompt_text("Task goal", input_stream, output, default=f"Implement {task_id}")
    stage = prompt_choice("Start stage", WIZARD_STAGES, input_stream, output, default="CLARIFYING")
    current_step = prompt_text("Current step id", input_stream, output, default="")
    create_plan = confirm_action("Create or replace .agent/plan.yaml?", input_stream, output)

    state = save_state(
        root_dir,
        {
            "task_id": task_id,
            "stage": stage,
            "current_step": current_step or None,
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
