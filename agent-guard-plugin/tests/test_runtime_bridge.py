import json
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
