from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import append_event
from .state import failures_path, load_state, save_state

DEFAULT_REPEAT_THRESHOLD = 2


def read_failures(root_dir: Path) -> dict[str, Any]:
    return json.loads(failures_path(root_dir).read_text(encoding="utf-8"))


def save_failures(root_dir: Path, failures: dict[str, Any]) -> dict[str, Any]:
    failures_path(root_dir).write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    return failures


def hash_failure(command: str, exit_code: int, log_path: Path | None) -> str:
    log_contents = log_path.read_text(encoding="utf-8") if log_path and log_path.exists() else ""
    digest = hashlib.sha256()
    digest.update(f"{command}\n{exit_code}\n{log_contents}".encode("utf-8"))
    return digest.hexdigest()


def latest_mtime(root_dir: Path) -> int:
    latest = 0
    for entry_name in ("src", "tests"):
        candidate = root_dir / entry_name
        if not candidate.exists():
            continue
        for item in [candidate, *candidate.rglob("*")]:
            latest = max(latest, int(item.stat().st_mtime_ns))
    return latest


def record_command_result(root_dir: Path, command: str, exit_code: int, log_path: str | None) -> dict[str, Any]:
    state = load_state(root_dir)
    absolute_log = (root_dir / log_path) if log_path else None
    failure_hash = None if exit_code == 0 else hash_failure(command, exit_code, absolute_log)
    failures = read_failures(root_dir)
    code_fingerprint = latest_mtime(root_dir)

    last_failure = failures.get("last_failure")
    if exit_code == 0:
        last_failure = None
    else:
        same_failure = (
            last_failure is not None
            and last_failure.get("command") == command
            and last_failure.get("failure_hash") == failure_hash
            and last_failure.get("code_fingerprint") == code_fingerprint
        )
        last_failure = {
            "command": command,
            "exit_code": exit_code,
            "failure_hash": failure_hash,
            "repeat_count": (last_failure["repeat_count"] + 1) if same_failure else 1,
            "code_changed_since_last_failure": not same_failure,
            "code_fingerprint": code_fingerprint,
            "log_path": log_path,
        }

    save_failures(root_dir, {"last_failure": last_failure})

    next_state = dict(state)
    is_expected_red_failure = state.get("stage") == "RED_TEST" and exit_code != 0
    if not is_expected_red_failure and exit_code != 0:
        next_state["stage"] = "NEEDS_FAILURE_ANALYSIS"
    if state.get("stage") == "VERIFY":
        next_state["last_verification"] = {
            "command": command,
            "exit_code": exit_code,
            "log_path": log_path,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    save_state(root_dir, next_state)

    event = append_event(
        root_dir,
        {
            "hook": "AfterCommand",
            "command": command,
            "exit_code": exit_code,
            "stage": next_state.get("stage"),
            **({"log_path": log_path} if log_path else {}),
        },
    )
    return {"state": next_state, "failure": last_failure, "event": event}


def check_failure_loop(root_dir: Path, threshold: int = DEFAULT_REPEAT_THRESHOLD) -> dict[str, Any]:
    failures = read_failures(root_dir)
    last_failure = failures.get("last_failure")
    if not last_failure:
        return {"decision": "allow", "reason": "No recorded failure loop."}

    if (
        last_failure.get("repeat_count", 0) >= threshold
        and last_failure.get("code_changed_since_last_failure") is False
    ):
        return {
            "decision": "block",
            "reason": (
                "Repeated identical failure detected without code changes. "
                "Write .agent/artifacts/failure-analysis.md before retrying."
            ),
            "failure": last_failure,
        }

    return {"decision": "allow", "reason": "Failure loop threshold not reached.", "failure": last_failure}
