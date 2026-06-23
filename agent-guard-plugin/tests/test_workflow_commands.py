"""Tests for test workflow commands."""
from pathlib import Path

from agent_guard.workflow_spec import complete_step_allowed_from_stages

from .helpers import setup_default_workflow


def test_complete_step_allowed_stages_are_declared_in_workflow_spec(monkeypatch, tmp_path: Path) -> None:
    """Test that complete step allowed stages are declared in workflow spec."""
    setup_default_workflow(monkeypatch, tmp_path)
    stages = complete_step_allowed_from_stages()
    assert sorted(stages) == sorted(["RED_TEST", "GREEN_IMPL", "REVIEW", "VERIFY"])
