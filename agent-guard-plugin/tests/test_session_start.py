"""Tests for test session start."""
from agent_guard.runtime_adapter import get_session_reminder
from agent_guard.task_reset import reset_task
import os

from .helpers import make_temp_repo, write_state


def test_session_start_includes_meta_skill_and_workflow_context() -> None:
    """Test that session start includes meta skill and workflow context."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="password-reset",
        stage="RED_TEST",
        current_step="red-001",
        remaining_steps=["red-001", "green-001"],
        can_finalize=False,
    )

    reminder = get_session_reminder(root_dir)

    assert reminder["meta_skill"]["path"] == "docs/skills/using-workflow.md"
    assert reminder["workflow"]["workflow_metadata"]["id"] == "standard-ddd-example"
    assert reminder["workflow"]["policy_roles"]["globals"]["paths"] == "hard_gate"
    assert reminder["workflow"]["stage_policy"]["intent"]["goal"] == reminder["workflow"]["current_stage_goal"]
    assert reminder["workflow"]["stage_policy"]["permissions"]["write"]["allow"] == ["tests/**"]
    assert reminder["workflow"]["soft_prompt"]["goal"] == reminder["workflow"]["current_stage_goal"]
    assert reminder["workflow"]["hard_gates"]["write_allow"] == ["tests/**"]
    assert reminder["workflow"]["current_stage_goal"]
    assert "GREEN_IMPL" in reminder["workflow"]["transitions_out"]
    assert reminder["workflow"]["transition_graph_mermaid"]
    assert any(skill["id"] == "plan-yaml" for skill in reminder["workflow"]["skill_catalog"])
    assert reminder["workflow"]["stage_writable_paths"] == ["tests/**"]
    assert reminder["workflow"]["stage_denied_paths"] == ["src/**"]
    assert reminder["workflow"]["stage_expected_artifacts"] == [".agent/artifacts/red-test.log"]
    assert reminder["workflow"]["stage_required_artifacts"] == []
    assert reminder["workflow"]["complete_step_allowed_from_stages"] == ["RED_TEST", "GREEN_IMPL", "REVIEW", "VERIFY"]
    assert "# Using Workflow" in reminder["prompt_block"]
    assert "Soft guidance:" in reminder["prompt_block"]
    assert "Hard gates:" in reminder["prompt_block"]
    assert "Allowed actions:" in reminder["prompt_block"]
    assert "Transition graph (mermaid):" in reminder["prompt_block"]
    assert "Allowed paths:" not in reminder["prompt_block"]
    assert "Forbidden paths:" not in reminder["prompt_block"]
    assert "Stage writable paths:" in reminder["prompt_block"]
    assert "Stage denied paths:" in reminder["prompt_block"]
    assert "Stage expected artifacts:" in reminder["prompt_block"]
    assert "Stage required artifacts:" in reminder["prompt_block"]
    assert "Complete-step allowed from:" in reminder["prompt_block"]
    assert "Automatic transitions:" not in reminder["prompt_block"]
    assert "Workflow commands:" not in reminder["prompt_block"]
    assert "Do not modify .agent/state.json directly" in reminder["prompt_block"]


def test_session_start_uses_claude_skill_layout_when_configured() -> None:
    """Test that session start uses claude skill layout when configured."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="RED_TEST")
    skills_dir = root_dir / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for skill_id, title in (
        ("using-workflow", "Using Workflow"),
        ("workflow-core", "Core Workflow"),
        ("failure-analysis", "Failure Analysis"),
        ("finalization-checklist", "Finalization Checklist"),
    ):
        skill_file = skills_dir / skill_id / "SKILL.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(f"# {title}\n", encoding="utf-8")
    previous = os.environ.get("AGENT_GUARD_SKILLS_DIR")
    os.environ["AGENT_GUARD_SKILLS_DIR"] = str(skills_dir)
    try:
        reminder = get_session_reminder(root_dir)
    finally:
        if previous is None:
            os.environ.pop("AGENT_GUARD_SKILLS_DIR", None)
        else:
            os.environ["AGENT_GUARD_SKILLS_DIR"] = previous

    workflow_core = next(skill for skill in reminder["workflow"]["skill_catalog"] if skill["id"] == "workflow-core")
    assert reminder["meta_skill"]["absolute_path"].endswith(".claude/skills/using-workflow/SKILL.md")
    assert workflow_core["absolute_path"].endswith(".claude/skills/workflow-core/SKILL.md")
    assert "# Using Workflow" in reminder["prompt_block"]


def test_session_start_includes_recent_archive_after_reset() -> None:
    """Test that session start includes recent archive after reset."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="old-task",
        stage="DONE",
        current_step="verify-001",
        can_finalize=True,
    )
    reset_task(root_dir, "new-task")

    reminder = get_session_reminder(root_dir)

    assert reminder["recent_archive"] is not None
    assert reminder["recent_archive"]["archived_task_id"] == "old-task"
    assert "Last archived task: old-task" in reminder["prompt_block"]


def test_session_start_defaults_to_idle_when_agent_dir_is_missing() -> None:
    """Test that session start defaults to idle when agent dir is missing."""
    root_dir = make_temp_repo()
    for child in (root_dir / ".agent").rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted((root_dir / ".agent").rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    (root_dir / ".agent").rmdir()

    reminder = get_session_reminder(root_dir)

    assert reminder["task"] is None
    assert reminder["stage"] == "IDLE"
    assert reminder["current_step"] is None
    assert reminder["next_required_action"] is None
    assert "explore repository directories and files in read-only mode" in reminder["workflow"]["allowed_actions"]
    assert "modify files before a task is started" in reminder["workflow"]["forbidden_actions"]
