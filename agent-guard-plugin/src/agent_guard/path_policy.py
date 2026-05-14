"""Path-policy checks that gate file writes by workflow stage."""
from __future__ import annotations

from typing import Any

from .domain.models import TaskSession
from .domain.policies import WorkflowPolicyService
from .workflow_spec import stage_spec


def stage_rule_for(stage: str) -> dict[str, Any]:
    """Return the stage workflow rule block."""
    return stage_spec(stage)


def decide_write(state: dict[str, Any], target_path: str) -> dict[str, str]:
    """Decide write."""
    session = TaskSession.from_mapping(state)
    decision = WorkflowPolicyService().decide_write(session, target_path, stage_rule_for(session.stage))
    return decision.to_mapping()
