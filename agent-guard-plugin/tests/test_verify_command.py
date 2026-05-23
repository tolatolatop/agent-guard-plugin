"""Tests for the verify convenience command."""
from __future__ import annotations

import json
import sys

import pytest

from agent_guard.cli import run_command
from agent_guard.state import load_state, record_stage_artifact_snapshot

from .helpers import make_temp_repo, write_state


def _write_terminal_plan(root_dir):
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: verify-command\n"
        "steps:\n"
        "  - id: verify-001\n"
        "    stage: VERIFY\n"
        "    goal: run verification\n"
        "    status: done\n",
        encoding="utf-8",
    )


def test_verify_auto_ready_runs_command_records_verification_and_advances(capsys: pytest.CaptureFixture[str]) -> None:
    """verify --auto-ready should record successful verification and move to the ready stage."""
    root_dir = make_temp_repo()
    _write_terminal_plan(root_dir)
    test_file = root_dir / "test_sample.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    write_state(root_dir, task_id="verify-command", stage="VERIFY")
    record_stage_artifact_snapshot(root_dir, "VERIFY", None)

    with pytest.raises(SystemExit) as exc:
        run_command(["verify", "--auto-ready", "--", sys.executable, "-m", "pytest", "-q", str(test_file)], root_dir)

    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["verification"]["exit_code"] == 0
    assert payload["ready"] is not None

    state = load_state(root_dir)
    assert state["stage"] == "READY_TO_SUMMARIZE"
    assert state["can_finalize"] is True
    assert state["last_verification"]["exit_code"] == 0
    assert "pytest" in state["last_verification"]["command"]
    log_path = root_dir / state["last_verification"]["log_path"]
    assert log_path.exists()
    assert "command:" in log_path.read_text(encoding="utf-8")


def test_verify_records_failed_command_without_auto_ready(capsys: pytest.CaptureFixture[str]) -> None:
    """A failing verify command should record exit code and follow the failure policy."""
    root_dir = make_temp_repo()
    _write_terminal_plan(root_dir)
    test_file = root_dir / "test_sample.py"
    test_file.write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    write_state(root_dir, task_id="verify-command", stage="VERIFY")
    record_stage_artifact_snapshot(root_dir, "VERIFY", None)

    with pytest.raises(SystemExit) as exc:
        run_command(["verify", "--auto-ready", "--", sys.executable, "-m", "pytest", "-q", str(test_file)], root_dir)

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["verification"]["exit_code"] == 1
    assert payload["ready"] is None

    state = load_state(root_dir)
    assert state["stage"] == "NEEDS_FAILURE_ANALYSIS"
    assert state["can_finalize"] is False
    assert state["last_verification"]["exit_code"] == 1
