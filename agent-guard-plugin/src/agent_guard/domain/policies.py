"""Policy services driven by workflow spec plus repositories."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import FailureRecord, GuardDecision, TaskSession, VerificationRecord
from .rules import RuleContext, evaluate_rule
from ..managed_documents import (
    ManagedDocumentKind,
    ManagedDocumentOperation,
    ManagedDocumentPolicyService,
    managed_document_backing_path,
    managed_document_kind_for_path,
)
from ..events import append_event
from ..infrastructure.repositories import FailuresRepository, JobsRepository, StateRepository
from ..workflow_spec import (
    canonical_expected_failure_stage,
    canonical_failure_analysis_stage,
    canonical_verification_stage,
    failure_policy,
    finalization_policy,
    path_policy,
    stage_required_artifact_rules,
)


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

    @staticmethod
    def _write_payload(session: TaskSession, writable_paths: list[str], denied_paths: list[str]) -> dict[str, Any]:
        """Build structured write-policy context for CLI and hooks."""
        return {
            "stage": session.stage,
            "writable_paths": list(writable_paths),
            "denied_paths": list(denied_paths),
        }

    def _blocked_write_decision(
        self,
        session: TaskSession,
        reason: str,
        writable_paths: list[str],
        denied_paths: list[str],
    ) -> GuardDecision:
        """Build one blocked write decision with actionable guidance."""
        payload = self._write_payload(session, writable_paths, denied_paths)
        if writable_paths:
            display_reason = f"{reason} Allowed write paths during {session.stage}: {', '.join(writable_paths)}."
        else:
            display_reason = f"{reason} Current stage {session.stage} does not allow agent writes."
        payload["display_reason"] = display_reason
        return GuardDecision("block", display_reason, payload=payload)

    def decide_write(self, session: TaskSession, target_path: str, stage_rule: dict[str, Any], root_dir: Path | None = None) -> GuardDecision:
        """Decide whether the current session may write the target path."""
        normalized = normalize_path(target_path)
        policy = path_policy(root_dir, session.workflow_id)
        stage_write_policy = stage_rule.get("write_policy", {})
        writable_paths = [str(item) for item in stage_write_policy.get("writable_paths", [])]
        denied_paths = [str(item) for item in stage_write_policy.get("denied_paths", [])]
        document_kind = managed_document_kind_for_path(normalized)

        if document_kind == ManagedDocumentKind.SESSION_STATE:
            decision = ManagedDocumentPolicyService().decide_write(
                session,
                document_kind,
                ManagedDocumentOperation.DIRECT_WRITE,
                root_dir=root_dir,
                stage_rule=stage_rule,
            )
            return self._blocked_write_decision(
                session,
                decision.reason,
                writable_paths,
                denied_paths,
            )

        if not session.has_active_task and not matches_any(normalized, writable_paths):
            return self._blocked_write_decision(
                session,
                f"No active task is set and stage is {session.stage}. Run agent-guard start-task before writing project files.",
                writable_paths,
                denied_paths,
            )

        if document_kind == ManagedDocumentKind.WORKFLOW_PLAN:
            decision = ManagedDocumentPolicyService().decide_write(
                session,
                document_kind,
                ManagedDocumentOperation.DIRECT_WRITE,
                root_dir=root_dir,
                stage_rule=stage_rule,
            )
            if decision.allowed:
                return GuardDecision(
                    "allow",
                    decision.reason,
                    payload=self._write_payload(session, writable_paths, denied_paths),
                )
            return self._blocked_write_decision(
                session,
                decision.reason,
                writable_paths,
                denied_paths,
            )

        if matches_any(normalized, policy["protected_paths"]):
            return self._blocked_write_decision(
                session,
                f"Path {normalized} is managed by agent-guard and cannot be edited directly.",
                writable_paths,
                denied_paths,
            )

        if matches_any(normalized, denied_paths):
            return self._blocked_write_decision(
                session,
                f"Path {normalized} is denied during {session.stage}.",
                writable_paths,
                denied_paths,
            )

        if matches_any(normalized, policy["sensitive_paths"]) and not matches_any(normalized, writable_paths):
            return self._blocked_write_decision(
                session,
                f"Path {normalized} is sensitive and not writable during {session.stage}.",
                writable_paths,
                denied_paths,
            )

        if not writable_paths:
            return self._blocked_write_decision(
                session,
                f"Path {normalized} is not writable during {session.stage}.",
                writable_paths,
                denied_paths,
            )

        if matches_any(normalized, writable_paths):
            return GuardDecision(
                "allow",
                f"Path {normalized} is allowed during {session.stage}.",
                payload=self._write_payload(session, writable_paths, denied_paths),
            )

        if session.stage == "IDLE":
            return self._blocked_write_decision(
                session,
                f"No active task is set and stage is {session.stage}. Run agent-guard start-task before writing project files.",
                writable_paths,
                denied_paths,
            )

        return self._blocked_write_decision(
            session,
            f"Path {normalized} is not writable during {session.stage}.",
            writable_paths,
            denied_paths,
        )


class StageExitPolicyService:
    """Policy service for required-artifact exit gating."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.state_repo = StateRepository(root_dir)

    def _artifact_mtime_ns(self, artifact_path: str) -> int | None:
        candidate = (
            managed_document_backing_path(self.root_dir, artifact_path)
            if managed_document_kind_for_path(artifact_path) is not None
            else self.root_dir / artifact_path
        )
        if not candidate.exists():
            return None
        return int(candidate.stat().st_mtime_ns)

    def exit_failures(self, stage: str) -> list[str]:
        """Return required-artifact exit failures for one stage."""
        from ..state import ensure_stage_artifact_snapshot, load_stage_artifact_snapshot

        session = self.state_repo.load()
        required_rules = stage_required_artifact_rules(stage, self.root_dir, session.workflow_id)
        if not required_rules:
            return []

        ensure_stage_artifact_snapshot(self.root_dir, stage, session.workflow_id)
        snapshot = load_stage_artifact_snapshot(self.root_dir)
        entered_at = snapshot.get("entered_at") or "the current stage"
        recorded = snapshot.get("artifacts", {})
        failures: list[str] = []
        for rule in required_rules:
            artifact_path = rule["path"]
            current_mtime = self._artifact_mtime_ns(artifact_path)
            previous_mtime = None
            details = recorded.get(artifact_path)
            if isinstance(details, dict):
                previous_mtime = details.get("mtime_ns")
            if current_mtime is None:
                failures.append(f"{artifact_path} must exist and be updated after entering {stage} at {entered_at}.")
                continue
            if previous_mtime is not None and int(current_mtime) <= int(previous_mtime):
                failures.append(f"{artifact_path} must be updated after entering {stage} at {entered_at}.")
                continue
            matches = rule.get("matches")
            if matches:
                contents = (self.root_dir / artifact_path).read_text(encoding="utf-8")
                if re.search(matches, contents, re.MULTILINE) is None:
                    failures.append(rule.get("message") or f"{artifact_path} does not match the required format.")
        return failures


class FailurePolicyService:
    """Policy service for command recording and failure-loop detection."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.state_repo = StateRepository(root_dir)
        self.failures_repo = FailuresRepository(root_dir)

    def latest_code_fingerprint(self) -> int:
        """Return a fingerprint of tracked code roots."""
        latest = 0
        session = self.state_repo.load()
        for entry_name in failure_policy(self.root_dir, session.workflow_id)["fingerprint_roots"]:
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
        execution_stage = session.stage
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

        expected_failure_stage = canonical_expected_failure_stage(self.root_dir, session.workflow_id)
        analysis_stage = canonical_failure_analysis_stage(self.root_dir, session.workflow_id)
        verification_stage = canonical_verification_stage(self.root_dir, session.workflow_id)
        expected_red_failure = session.stage == expected_failure_stage and exit_code != 0
        next_session = session
        if exit_code != 0 and not expected_red_failure and analysis_stage:
            next_session = next_session.enter_failure_analysis(analysis_stage)
        if verification_stage and session.stage == verification_stage:
            next_session = next_session.record_verification(
                VerificationRecord(
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
                "stage": execution_stage,
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
        session = self.state_repo.load()
        policy = failure_policy(self.root_dir, session.workflow_id)
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
        rules = finalization_policy(self.root_dir, session.workflow_id)["required_rules"]
        context = RuleContext(self.root_dir, session)
        reasons: list[str] = []
        for rule_name in rules:
            if evaluate_rule(rule_name, context):
                continue
            reasons.append(finalization_policy(self.root_dir, session.workflow_id)["rule_messages"].get(rule_name, f"{rule_name} must pass"))

        if reasons:
            return GuardDecision("block", reasons[0], reasons=reasons)
        return GuardDecision("allow", "Finalization policy passed.", reasons=[])
