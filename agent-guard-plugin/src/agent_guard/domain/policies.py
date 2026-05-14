"""Policy services driven by workflow spec plus repositories."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import FailureRecord, GuardDecision, TaskSession, VerificationRecord
from .rules import RuleContext, evaluate_rule
from ..events import append_event
from ..infrastructure.repositories import FailuresRepository, JobsRepository, StateRepository
from ..workflow_spec import failure_policy, finalization_policy, path_policy


def normalize_path(target_path: str) -> str:
    """Normalize repo-relative paths for policy checks."""
    normalized = target_path.replace("\\", "/").removeprefix("./")
    if normalized == ".agent" or normalized.startswith(".agent/"):
        return normalized
    agent_marker = "/.agent/"
    if agent_marker in normalized:
        return ".agent/" + normalized.rsplit(agent_marker, 1)[1].lstrip("/")
    if normalized.endswith("/.agent"):
        return ".agent"
    return normalized


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a simple glob to a regex."""
    normalized = normalize_path(pattern)
    double_placeholder = "__DOUBLE_WILDCARD__"
    single_placeholder = "__SINGLE_WILDCARD__"
    escaped = normalized.replace("**", double_placeholder).replace("*", single_placeholder)
    escaped = re.escape(escaped)
    regex_source = escaped.replace(double_placeholder, ".*").replace(single_placeholder, "[^/]*")
    return re.compile(f"^{regex_source}$")


def matches_any(target_path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """Return whether the path matches any glob."""
    normalized = normalize_path(target_path)
    return any(glob_to_regex(pattern).match(normalized) for pattern in patterns)


class WorkflowPolicyService:
    """Policy service for write scope and path protection."""

    def decide_write(self, session: TaskSession, target_path: str, stage_rule: dict[str, Any]) -> GuardDecision:
        """Decide whether the current session may write the target path."""
        normalized = normalize_path(target_path)
        policy = path_policy()
        stage_write_policy = stage_rule.get("write_policy", {})
        writable_paths = [str(item) for item in stage_write_policy.get("writable_paths", [])]
        denied_paths = [str(item) for item in stage_write_policy.get("denied_paths", [])]

        if matches_any(normalized, policy["protected_paths"]):
            return GuardDecision(
                "block",
                "Path .agent/state.json is managed by agent-guard and cannot be edited directly. Use agent-guard commands to change task state.",
            )

        if not session.has_active_task and not matches_any(normalized, writable_paths):
            return GuardDecision(
                "block",
                f"No active task is set and stage is {session.stage}. Run agent-guard start-task before writing project files.",
            )

        if matches_any(normalized, denied_paths):
            return GuardDecision("block", f"Path {normalized} is denied during {session.stage}.")

        if matches_any(normalized, policy["sensitive_paths"]) and not matches_any(normalized, writable_paths):
            return GuardDecision("block", f"Path {normalized} is sensitive and not writable during {session.stage}.")

        if not writable_paths:
            return GuardDecision("block", f"Current stage is {session.stage}. No writable paths are configured.")

        if matches_any(normalized, writable_paths):
            return GuardDecision("allow", f"Path {normalized} is allowed during {session.stage}.")

        if session.stage == "IDLE":
            return GuardDecision(
                "block",
                f"No active task is set and stage is {session.stage}. Run agent-guard start-task before writing project files.",
            )

        return GuardDecision("block", f"Path {normalized} is not writable during {session.stage}.")


class FailurePolicyService:
    """Policy service for command recording and failure-loop detection."""

    EXPECTED_FAILURE_STAGE = "RED_TEST"
    ANALYSIS_STAGE = "NEEDS_FAILURE_ANALYSIS"

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.state_repo = StateRepository(root_dir)
        self.failures_repo = FailuresRepository(root_dir)

    def latest_code_fingerprint(self) -> int:
        """Return a fingerprint of tracked code roots."""
        latest = 0
        for entry_name in failure_policy()["fingerprint_roots"]:
            candidate = self.root_dir / entry_name
            if not candidate.exists():
                continue
            for item in [candidate, *candidate.rglob("*")]:
                latest = max(latest, int(item.stat().st_mtime_ns))
        return latest

    def hash_failure(self, command: str, exit_code: int, log_path: Path | None) -> str:
        """Hash a failed command and its evidence."""
        log_contents = log_path.read_text(encoding="utf-8") if log_path and log_path.exists() else ""
        digest = hashlib.sha256()
        digest.update(f"{command}\n{exit_code}\n{log_contents}".encode("utf-8"))
        return digest.hexdigest()

    def record_command_execution(self, command: str, exit_code: int, log_path: str | None) -> dict[str, Any]:
        """Record command evidence and update session state."""
        session = self.state_repo.load()
        absolute_log = (self.root_dir / log_path) if log_path else None
        fingerprint = self.latest_code_fingerprint()
        last_failure = self.failures_repo.load()
        failure: FailureRecord | None = None

        if exit_code != 0:
            failure_hash = self.hash_failure(command, exit_code, absolute_log)
            same_failure = (
                last_failure is not None
                and last_failure.command == command
                and last_failure.failure_hash == failure_hash
                and last_failure.code_fingerprint == fingerprint
            )
            failure = FailureRecord(
                command=command,
                exit_code=exit_code,
                failure_hash=failure_hash,
                repeat_count=(last_failure.repeat_count + 1) if same_failure and last_failure else 1,
                code_changed_since_last_failure=not same_failure,
                code_fingerprint=fingerprint,
                log_path=log_path,
            )
        self.failures_repo.save(failure)

        expected_red_failure = session.stage == self.EXPECTED_FAILURE_STAGE and exit_code != 0
        next_session = session
        if exit_code != 0 and not expected_red_failure:
            next_session = next_session.with_updates(stage=self.ANALYSIS_STAGE)
        if session.stage == "VERIFY":
            next_session = next_session.with_updates(
                last_verification=VerificationRecord(
                    command=command,
                    exit_code=exit_code,
                    log_path=log_path,
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        self.state_repo.save(next_session)

        event = append_event(
            self.root_dir,
            {
                "hook": "AfterCommand",
                "command": command,
                "exit_code": exit_code,
                "stage": next_session.stage,
                **({"log_path": log_path} if log_path else {}),
            },
        )
        return {
            "state": next_session.to_mapping(),
            "failure": failure.to_mapping() if failure else None,
            "event": event,
        }

    def check_failure_loop(self) -> GuardDecision:
        """Check whether identical failures must be analyzed before retry."""
        record = self.failures_repo.load()
        if record is None:
            return GuardDecision("allow", "No recorded failure loop.")
        policy = failure_policy()
        if record.repeat_count >= policy["repeat_threshold"] and record.code_changed_since_last_failure is False:
            return GuardDecision(
                "block",
                "Repeated identical failure detected without code changes. Perform failure analysis before retrying.",
                payload={"failure": record.to_mapping()},
            )
        return GuardDecision(
            "allow",
            "Failure loop threshold not reached.",
            payload={"failure": record.to_mapping()},
        )


class JobPolicyService:
    """Policy service for job polling guard checks."""

    DEFAULT_MAX_POLLS = 20

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def check_poll(self, job_id: str) -> GuardDecision:
        """Check whether a running job may be polled now."""
        job = next((entry for entry in JobsRepository(self.root_dir).load_jobs() if entry.id == job_id), None)
        if job is None:
            return GuardDecision("block", f"Unknown job id: {job_id}")
        if job.status != "running":
            return GuardDecision("allow", f"Job {job_id} is already {job.status}.")
        if job.next_poll_after:
            now = datetime.now(timezone.utc)
            if now < datetime.fromisoformat(job.next_poll_after.replace("Z", "+00:00")):
                return GuardDecision("block", f"Job {job_id} cannot be polled before {job.next_poll_after}.")
        max_polls = job.max_polls if job.max_polls is not None else self.DEFAULT_MAX_POLLS
        if job.poll_count >= max_polls:
            return GuardDecision("block", f"Job {job_id} exceeded max poll count and requires human review.")
        return GuardDecision("allow", f"Job {job_id} can be polled now.")


class FinalizationPolicyService:
    """Policy service for finalization gates."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def evaluate(self, session: TaskSession) -> GuardDecision:
        """Evaluate the configured finalization policy."""
        rules = finalization_policy()["required_rules"]
        context = RuleContext(self.root_dir, session)
        reasons: list[str] = []
        for rule_name in rules:
            if evaluate_rule(rule_name, context):
                continue
            reasons.append(finalization_policy()["rule_messages"].get(rule_name, f"{rule_name} must pass"))

        if reasons:
            return GuardDecision("block", reasons[0], reasons=reasons)
        return GuardDecision("allow", "Finalization policy passed.", reasons=[])
