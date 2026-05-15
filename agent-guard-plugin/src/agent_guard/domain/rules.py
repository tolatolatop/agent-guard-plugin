"""Built-in workflow rule evaluator registry."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Callable

from .models import TaskSession
from ..infrastructure.repositories import JobsRepository, PlanRepository
from ..state import events_path, load_stage_artifact_snapshot


@dataclass(frozen=True)
class RuleContext:
    """Inputs used by workflow rule evaluation."""

    root_dir: Path
    session: TaskSession
    command_name: str | None = None


RuleEvaluator = Callable[[RuleContext, Any | None], bool]


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _command_matches(pattern: Any, command: str) -> bool:
    if not isinstance(pattern, str) or not pattern.strip():
        return False
    if command == pattern:
        return True
    return re.search(pattern, command) is not None


def _stage_command_events(context: RuleContext) -> list[dict[str, Any]]:
    snapshot = load_stage_artifact_snapshot(context.root_dir)
    entered_at = _parse_iso_timestamp(snapshot.get("entered_at"))
    current_stage = context.session.stage
    file_path = events_path(context.root_dir)
    if not file_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("hook") != "AfterCommand":
            continue
        if str(payload.get("stage")) != current_stage:
            continue
        if entered_at is not None:
            event_ts = _parse_iso_timestamp(payload.get("ts"))
            if event_ts is None or event_ts < entered_at:
                continue
        events.append(payload)
    return events


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
    plan = PlanRepository(context.root_dir).load_raw()
    if plan is None:
        return False
    return not any(step.status.strip().lower() not in {"done", "failed"} for step in PlanRepository(context.root_dir).load_steps())


def _review_artifact_present(context: RuleContext, value: Any | None) -> bool:
    target = str(value or ".agent/artifacts/review.md")
    return (context.root_dir / target).exists()


def _required_artifact_exists(context: RuleContext, value: Any | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return (context.root_dir / value).exists()


def _failure_analysis_present(context: RuleContext, value: Any | None) -> bool:
    target = str(value or ".agent/artifacts/failure-analysis.md")
    return (context.root_dir / target).exists()


def _can_finalize_flag(context: RuleContext, value: Any | None) -> bool:
    return context.session.can_finalize is True


def _can_finalize_passes(context: RuleContext, value: Any | None) -> bool:
    from ..gates import can_finalize

    return can_finalize(context.root_dir)["decision"] == "allow"


def _command_ran(context: RuleContext, value: Any | None) -> bool:
    return any(_command_matches(value, str(event.get("command", ""))) for event in _stage_command_events(context))


def _command_succeeded(context: RuleContext, value: Any | None) -> bool:
    return any(
        int(event.get("exit_code", 1)) == 0 and _command_matches(value, str(event.get("command", "")))
        for event in _stage_command_events(context)
    )


RULE_EVALUATORS: dict[str, RuleEvaluator] = {
    "required_command": _required_command,
    "active_task": _active_task,
    "successful_last_verification": _successful_last_verification,
    "no_running_jobs": _no_running_jobs,
    "all_plan_steps_terminal": _all_plan_steps_terminal,
    "review_artifact_present": _review_artifact_present,
    "required_artifact_exists": _required_artifact_exists,
    "failure_analysis_present": _failure_analysis_present,
    "can_finalize_flag": _can_finalize_flag,
    "can_finalize_passes": _can_finalize_passes,
    "command_ran": _command_ran,
    "command_succeeded": _command_succeeded,
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
