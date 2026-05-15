"""Application use cases for the workflow-driven engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.models import PlanStep
from ..domain.policies import FailurePolicyService, FinalizationPolicyService, JobPolicyService, WorkflowPolicyService
from ..infrastructure.repositories import StateRepository
from ..path_policy import stage_rule_for
from ..runtime_adapter import get_next_step, get_session_reminder
from ..state import AGENT_DIR, ensure_agent_files
from ..workflow_spec import canonical_entry_stage


def initialize_workspace(root_dir: Path) -> dict[str, Any]:
    """Initialize the managed .agent workspace."""
    ensure_agent_files(root_dir)
    return {"ok": True, "agent_dir": str(root_dir / AGENT_DIR)}


def start_task(root_dir: Path, task_id: str) -> dict[str, Any]:
    """Start or register a task session."""
    ensure_agent_files(root_dir)
    repo = StateRepository(root_dir)
    session = repo.load()
    updated = repo.save(session.start(task_id, entry_stage=canonical_entry_stage()))
    return {"ok": True, "state": updated.to_mapping()}


def build_session_reminder(root_dir: Path) -> dict[str, Any]:
    """Build the runtime reminder projection."""
    return {"ok": True, **get_session_reminder(root_dir)}


def check_write_permission(root_dir: Path, target_path: str) -> dict[str, Any]:
    """Guard writes using the workflow policy service."""
    session = StateRepository(root_dir).load()
    decision = WorkflowPolicyService().decide_write(session, target_path, stage_rule_for(session.stage))
    return decision.to_mapping()


def record_command_execution(root_dir: Path, command: str, exit_code: int, log_path: str | None) -> dict[str, Any]:
    """Record command evidence and state transitions."""
    return FailurePolicyService(root_dir).record_command_execution(command, exit_code, log_path)


def check_failure_loop(root_dir: Path) -> dict[str, Any]:
    """Guard retries after repeated equivalent failures."""
    return FailurePolicyService(root_dir).check_failure_loop().to_mapping()


def check_job_poll(root_dir: Path, job_id: str) -> dict[str, Any]:
    """Guard job polling cadence."""
    return JobPolicyService(root_dir).check_poll(job_id).to_mapping()


def check_finalization(root_dir: Path) -> dict[str, Any]:
    """Evaluate finalization gates."""
    session = StateRepository(root_dir).load()
    return FinalizationPolicyService(root_dir).evaluate(session).to_mapping()


def next_step(root_dir: Path) -> dict[str, Any]:
    """Resolve the next step projection."""
    session = StateRepository(root_dir).load()
    return {"ok": True, "next_step": get_next_step(root_dir, session.to_mapping())}


def plan_template_step(task_id: str, stage: str, step_id: str | None, goal: str) -> PlanStep:
    """Create the default structured plan step for the wizard."""
    commands: list[str] = []
    if stage == "RED_TEST":
        commands = ["pytest"]
    elif stage == "GREEN_IMPL":
        commands = ["pytest"]
    return PlanStep(
        id=step_id or ("red-001" if stage == "RED_TEST" else "green-001" if stage == "GREEN_IMPL" else "step-001"),
        goal=goal,
        status="in_progress" if stage in {"PLANNING", "RED_TEST", "GREEN_IMPL"} else "pending",
        stage=stage,
        commands=commands,
    )
