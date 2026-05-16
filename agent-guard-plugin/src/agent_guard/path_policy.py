"""Path-policy checks that gate file writes by workflow stage."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .domain.models import TaskSession
from .domain.policies import WorkflowPolicyService
from .workflow_spec import stage_spec


def stage_rule_for(stage: str, root_dir: Path | None = None, workflow_id: str | None = None) -> dict[str, Any]:
    """Return the stage workflow rule block."""
    return stage_spec(stage, root_dir, workflow_id)


def decide_write(state: dict[str, Any], target_path: str, root_dir: Path | None = None) -> dict[str, str]:
    """Decide write."""
    session = TaskSession.from_mapping(state)
    decision = WorkflowPolicyService().decide_write(
        session,
        target_path,
        stage_rule_for(session.stage, root_dir, session.workflow_id),
        root_dir,
    )
    return decision.to_mapping()
