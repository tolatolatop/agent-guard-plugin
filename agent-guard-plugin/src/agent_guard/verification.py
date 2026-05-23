"""Convenience verification command implementation."""
from __future__ import annotations

import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .application.use_cases import record_command_execution
from .state import artifacts_dir, load_state
from .transitions import ready_to_summarize
from .workflow_spec import canonical_verification_stage


def split_verify_args(args: list[str]) -> tuple[bool, list[str]]:
    """Parse verify flags and return (auto_ready, command_argv)."""
    auto_ready = False
    command_start: int | None = None
    for index, item in enumerate(args):
        if item == "--":
            command_start = index + 1
            break
        if item == "--auto-ready":
            auto_ready = True
            continue
        raise RuntimeError(f"Unknown verify option: {item}")
    if command_start is None:
        raise RuntimeError("Usage: agent-guard verify [--auto-ready] -- <command>")
    command = args[command_start:]
    if not command:
        raise RuntimeError("verify requires a command after --")
    return auto_ready, command


def _write_final_verification_log(root_dir: Path, command: str, completed: subprocess.CompletedProcess[str]) -> str:
    """Write final verification evidence and return the repo-relative path."""
    target = artifacts_dir(root_dir) / "final-verification.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        f"command: {command}",
        f"exit_code: {completed.returncode}",
        f"recorded_at: {datetime.now(timezone.utc).isoformat()}",
    ]
    if completed.stdout:
        parts.extend(["", "stdout:", completed.stdout.rstrip()])
    if completed.stderr:
        parts.extend(["", "stderr:", completed.stderr.rstrip()])
    target.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return target.relative_to(root_dir).as_posix()


def run_verification_command(root_dir: Path, args: list[str]) -> tuple[int, dict[str, Any]]:
    """Run a verification command, record last_verification, and optionally mark ready."""
    auto_ready, command_argv = split_verify_args(args)
    state = load_state(root_dir)
    workflow_id = str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None
    verification_stage = canonical_verification_stage(root_dir, workflow_id)
    if state.get("stage") != verification_stage:
        raise RuntimeError(f"verify is only allowed in {verification_stage}; current stage is {state.get('stage')}")

    command_text = shlex.join(command_argv)
    completed = subprocess.run(
        command_argv,
        cwd=root_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    log_path = _write_final_verification_log(root_dir, command_text, completed)
    record_result = record_command_execution(root_dir, command_text, int(completed.returncode), log_path)

    ready_result = None
    if auto_ready and completed.returncode == 0:
        ready_result = ready_to_summarize(root_dir)

    payload: dict[str, Any] = {
        "ok": completed.returncode == 0,
        "command": command_text,
        "verification": {
            "exit_code": int(completed.returncode),
            "log_path": log_path,
        },
        "record": record_result,
        "ready": ready_result,
    }
    return int(completed.returncode), payload
