"""Tests for test runtime bridge."""
import json
import os
import subprocess
import sys

from agent_guard.state import save_state

from .helpers import make_temp_repo, runtime_test_env


def run_bridge(root_dir, action, payload):
    """Helper for run bridge."""
    return subprocess.run(
        [sys.executable, "-m", "agent_guard.runtime_bridge", action],
        cwd=root_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=runtime_test_env(),
    )


def test_bridge_blocks_forbidden_write() -> None:
    """Test that bridge blocks forbidden write."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "RED_TEST",
            "current_step": "red-001",
            "completed_steps": [],
            "remaining_steps": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    result = run_bridge(root_dir, "pre-write", {"tool_input": {"file_path": "src/app.py"}})
    assert result.returncode == 2
    assert "denied during RED_TEST" in result.stderr


def test_bridge_allows_absolute_agent_plan_write_within_repo() -> None:
    """Test that bridge allows absolute agent plan write within repo."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "implementation-plan",
            "stage": "PLANNING",
            "current_step": "plan-001",
            "completed_steps": [],
            "remaining_steps": ["plan-001"],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    result = run_bridge(
        root_dir,
        "pre-write",
        {"tool_input": {"file_path": str(root_dir / ".agent" / "plan.yaml")}},
    )
    assert result.returncode == 0


def test_bridge_records_final_verification_log_only_for_verify() -> None:
    """Test that bridge records final verification log only for verify."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "VERIFY",
            "current_step": "verify-001",
            "completed_steps": [],
            "remaining_steps": [],
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
    assert (root_dir / ".agent" / "artifacts" / "final-verification.log").exists()


def test_bridge_does_not_write_success_log_outside_verify() -> None:
    """Test that bridge does not write success log outside verify."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "GREEN_IMPL",
            "current_step": "green-001",
            "completed_steps": [],
            "remaining_steps": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )

    result = run_bridge(
        root_dir,
        "post-command",
        {"tool_input": {"command": "pytest tests/example.py"}, "tool_response": {"exit_code": 0, "stdout": "ok"}},
    )
    assert result.returncode == 0
    assert not list((root_dir / ".agent" / "artifacts").glob("*.log"))


def test_bridge_session_start_prefers_prompt_block_output() -> None:
    """Test that bridge session start prefers prompt block output."""
    root_dir = make_temp_repo()
    result = run_bridge(root_dir, "session-start", {})
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert payload["hookSpecificOutput"]["additionalContext"].startswith("AGENT-GUARD NAVIGATOR")


def test_bridge_stop_allows_clarifying() -> None:
    """Test that bridge stop allows clarifying."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "CLARIFYING",
            "current_step": None,
            "completed_steps": [],
            "remaining_steps": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 0
    assert result.stderr == ""


def test_bridge_stop_blocks_designing_when_stage_forbids_human_intervention() -> None:
    """Test that bridge stop blocks designing when stage forbids human intervention."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "DESIGNING",
            "current_step": "design-001",
            "completed_steps": [],
            "remaining_steps": ["design-001"],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 2
    assert "Current stage does not allow human intervention; continue advancing the task." in result.stderr


def test_bridge_stop_allows_planning() -> None:
    """Test that bridge stop allows planning."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "PLANNING",
            "current_step": "plan-001",
            "completed_steps": [],
            "remaining_steps": ["plan-001"],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 0
    assert result.stderr == ""


def test_bridge_stop_blocks_red_test() -> None:
    """Test that bridge stop blocks red test."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "RED_TEST",
            "current_step": "red-001",
            "completed_steps": [],
            "remaining_steps": ["red-001"],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 2
    assert "Current stage does not allow human intervention; continue advancing the task." in result.stderr


def test_bridge_stop_blocks_ready_to_summarize_when_stage_forbids_human_intervention() -> None:
    """Test that bridge stop blocks ready to summarize when stage forbids human intervention."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "READY_TO_SUMMARIZE",
            "current_step": None,
            "completed_steps": [],
            "remaining_steps": [],
            "can_finalize": True,
            "last_verification": {"exit_code": 0},
            "needs_human": False,
        },
    )

    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 2
    assert "Current stage does not allow human intervention; continue advancing the task." in result.stderr


def test_bridge_stop_allows_needs_human() -> None:
    """Test that bridge stop allows needs human."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "NEEDS_HUMAN",
            "current_step": None,
            "completed_steps": [],
            "remaining_steps": ["clarify-001"],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": True,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 0
    assert result.stderr == ""


def test_bridge_stop_allows_idle() -> None:
    """Test that bridge stop allows idle."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": None,
            "stage": "IDLE",
            "current_step": None,
            "completed_steps": [],
            "remaining_steps": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 0
    assert result.stderr == ""


def test_bridge_stop_allows_done_without_rechecking_finalize() -> None:
    """Test that bridge stop allows done without rechecking finalize."""
    root_dir = make_temp_repo()
    save_state(
        root_dir,
        {
            "task_id": "password-reset",
            "stage": "DONE",
            "current_step": None,
            "completed_steps": ["verify-001"],
            "remaining_steps": [],
            "can_finalize": False,
            "last_verification": None,
            "needs_human": False,
        },
    )
    result = run_bridge(root_dir, "stop", {})
    assert result.returncode == 0
    assert result.stderr == ""


def test_bridge_session_start_uses_installed_skills_dir() -> None:
    """Test that bridge session start uses installed skills dir."""
    root_dir = make_temp_repo()
    skills_dir = root_dir / ".agent-guard" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "using-workflow.md").write_text("nav\n", encoding="utf-8")
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
        env={**runtime_test_env(), "AGENT_GUARD_SKILLS_DIR": str(skills_dir)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "Using Workflow skill:" in payload["hookSpecificOutput"]["additionalContext"]
    assert "nav" in payload["hookSpecificOutput"]["additionalContext"]
