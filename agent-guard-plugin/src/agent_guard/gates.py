"""Finalization gates for workflow completion."""
from __future__ import annotations

from pathlib import Path

from .domain.policies import FinalizationPolicyService
from .infrastructure.repositories import StateRepository


def can_finalize(root_dir: Path) -> dict[str, object]:
    """Can finalize."""
    session = StateRepository(root_dir).load()
    decision = FinalizationPolicyService(root_dir).evaluate(session)
    return decision.to_mapping()
