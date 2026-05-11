import json
import os
import subprocess
import sys

from agent_guard.state import save_state

from .helpers import make_temp_repo


def run_bridge(root_dir, action, payload):
    return subprocess.run(
        [sys.executable, "-m", "agent_guard.runtime_bridge", action],
        cwd=root_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def test_bridge_blocks_forbidden_write() -> None:
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "RED_TEST",
            "current_step": "red-001",
            "completed_steps": [],
            "remaining_steps": [],
            "allowed_paths": ["tests/**"],
            "forbidden_paths": ["src/**"],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    result = run_bridge(root_dir, "pre-write", {"tool_input": {"file_path": "src/app.py"}})
    assert result.returncode == 2
    assert "src/** is forbidden" in result.stderr


def test_bridge_records_post_command_log() -> None:
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "VERIFY",
            "current_step": "verify-001",
            "completed_steps": [],
            "remaining_steps": [],
            "allowed_paths": [],
            "forbidden_paths": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    result = run_bridge(
        root_dir,
        "post-command",
        {"tool_input": {"command": "pytest"}, "tool_response": {"exit_code": 0, "stdout": "ok"}},
    )
    assert result.returncode == 0
    artifact_logs = list((root_dir / ".agent" / "artifacts").glob("hook-command-*.log"))
    assert artifact_logs


def test_bridge_session_start_prefers_prompt_block_output() -> None:
    root_dir = make_temp_repo()
    result = run_bridge(root_dir, "session-start", {})
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert payload["hookSpecificOutput"]["additionalContext"].startswith("AGENT-GUARD NAVIGATOR")


def test_bridge_stop_does_not_block_mid_task() -> None:
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "CLARIFYING",
            "current_step": None,
            "completed_steps": [],
            "remaining_steps": [],
            "allowed_paths": [],
            "forbidden_paths": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 0
    assert result.stderr == ""


def test_bridge_session_start_uses_installed_skills_dir() -> None:
    root_dir = make_temp_repo()
    skills_dir = root_dir / ".agent-guard" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "workflow-navigator.md").write_text("nav\n", encoding="utf-8")
    (skills_dir / "workflow-core.md").write_text("core\n", encoding="utf-8")
    (skills_dir / "failure-analysis.md").write_text("fail\n", encoding="utf-8")
    (skills_dir / "finalization-checklist.md").write_text("final\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "agent_guard.runtime_bridge", "session-start"],
        cwd=root_dir,
        input="{}",
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "AGENT_GUARD_SKILLS_DIR": str(skills_dir)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "workflow-navigator.md" in payload["hookSpecificOutput"]["additionalContext"]
