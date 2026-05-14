"""Built-in workflow rule evaluator registry."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import TaskSession
from ..infrastructure.repositories import JobsRepository, PlanRepository


@dataclass(frozen=True)
class RuleContext:
    """Inputs used by workflow rule evaluation."""

    root_dir: Path
    session: TaskSession
    command_name: str | None = None


RuleEvaluator = Callable[[RuleContext, Any | None], bool]


def _required_command(context: RuleContext, value: Any | None) -> bool:
    return context.command_name == str(value)


def _active_task(context: RuleContext, value: Any | None) -> bool:
    return context.session.has_active_task


def _successful_last_verification(context: RuleContext, value: Any | None) -> bool:
    verification = context.session.last_verification
    return verification is not None and verification.exit_code == 0


def _no_running_jobs(context: RuleContext, value: Any | None) -> bool:
    return not any(job.status == "running" for job in JobsRepository(context.root_dir).load_jobs())


def _all_plan_steps_terminal(context: RuleContext, value: Any | None) -> bool:
    return not any(step.status.strip().lower() not in {"done", "failed"} for step in PlanRepository(context.root_dir).load_steps())


def _review_artifact_present(context: RuleContext, value: Any | None) -> bool:
    target = str(value or ".agent/artifacts/review.json")
    return (context.root_dir / target).exists()


def _required_artifact_exists(context: RuleContext, value: Any | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return (context.root_dir / value).exists()


def _failure_analysis_present(context: RuleContext, value: Any | None) -> bool:
    target = str(value or ".agent/artifacts/failure-analysis.md")
    return (context.root_dir / target).exists()


def _remaining_steps_empty(context: RuleContext, value: Any | None) -> bool:
    return not context.session.remaining_steps


def _can_finalize_flag(context: RuleContext, value: Any | None) -> bool:
    return context.session.can_finalize is True


def _can_finalize_passes(context: RuleContext, value: Any | None) -> bool:
    from ..gates import can_finalize

    return can_finalize(context.root_dir)["decision"] == "allow"


RULE_EVALUATORS: dict[str, RuleEvaluator] = {
    "required_command": _required_command,
    "active_task": _active_task,
    "successful_last_verification": _successful_last_verification,
    "no_running_jobs": _no_running_jobs,
    "all_plan_steps_terminal": _all_plan_steps_terminal,
    "review_artifact_present": _review_artifact_present,
    "required_artifact_exists": _required_artifact_exists,
    "failure_analysis_present": _failure_analysis_present,
    "remaining_steps_empty": _remaining_steps_empty,
    "can_finalize_flag": _can_finalize_flag,
    "can_finalize_passes": _can_finalize_passes,
}


def allowed_rule_names() -> set[str]:
    """Return the allowed workflow rule vocabulary."""
    return set(RULE_EVALUATORS)


def evaluate_rule(name: str, context: RuleContext, value: Any | None = None) -> bool:
    """Evaluate one named built-in rule."""
    evaluator = RULE_EVALUATORS.get(name)
    if evaluator is None:
        raise RuntimeError(f"Unknown workflow rule: {name}")
    return evaluator(context, value)

