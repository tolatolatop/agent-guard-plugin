from agent_guard.runtime_adapter import get_session_reminder
from agent_guard.task_reset import reset_task
import os

from .helpers import make_temp_repo, write_state


def test_session_start_includes_meta_skill_and_workflow_context() -> None:
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="password-reset",
        stage="RED_TEST",
        current_step="red-001",
        remaining_steps=["red-001", "green-001"],
        allowed_paths=["tests/**"],
        forbidden_paths=["src/**"],
        can_finalize=False,
    )

    reminder = get_session_reminder(root_dir)

    assert reminder["meta_skill"]["path"] == "docs/skills/workflow-navigator.md"
    assert reminder["workflow"]["current_stage_goal"]
    assert "GREEN_IMPL" in reminder["workflow"]["transitions_out"]
    assert reminder["workflow"]["transition_graph"]
    assert reminder["workflow"]["workflow_commands"]
    assert "workflow-core.md" in reminder["prompt_block"]
    assert "Allowed actions:" in reminder["prompt_block"]
    assert "Workflow commands:" in reminder["prompt_block"]


def test_session_start_uses_claude_skill_layout_when_configured() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="RED_TEST")
    skills_dir = root_dir / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("AGENT_GUARD_SKILLS_DIR")
    os.environ["AGENT_GUARD_SKILLS_DIR"] = str(skills_dir)
    try:
        reminder = get_session_reminder(root_dir)
    finally:
        if previous is None:
            os.environ.pop("AGENT_GUARD_SKILLS_DIR", None)
        else:
            os.environ["AGENT_GUARD_SKILLS_DIR"] = previous

    assert reminder["meta_skill"]["absolute_path"].endswith(".claude/skills/workflow-navigator/SKILL.md")
    assert reminder["workflow"]["skill_catalog"][1]["absolute_path"].endswith(".claude/skills/workflow-core/SKILL.md")
    assert ".claude/skills/workflow-core/SKILL.md" in reminder["prompt_block"]


def test_session_start_includes_recent_archive_after_reset() -> None:
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
