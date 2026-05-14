"""Failure tracking and retry-loop protection helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain.policies import FailurePolicyService
from .state import failures_path


def read_failures(root_dir: Path) -> dict[str, Any]:
    """Read failures."""
    return json.loads(failures_path(root_dir).read_text(encoding="utf-8"))


def save_failures(root_dir: Path, failures: dict[str, Any]) -> dict[str, Any]:
    """Save failures."""
    failures_path(root_dir).write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    return failures


def record_command_result(root_dir: Path, command: str, exit_code: int, log_path: str | None) -> dict[str, Any]:
    """Record command result."""
    return FailurePolicyService(root_dir).record_command_execution(command, exit_code, log_path)


def check_failure_loop(root_dir: Path, threshold: int | None = None) -> dict[str, Any]:
    """Check failure loop."""
    return FailurePolicyService(root_dir).check_failure_loop().to_mapping()
