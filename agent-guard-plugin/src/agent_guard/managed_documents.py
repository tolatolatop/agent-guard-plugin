"""Managed .agent document policy and IO helpers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agent_guard_file_lock import (
    DEFAULT_PLAN_RELATIVE,
    DEFAULT_STATE_RELATIVE,
    fuse_enabled,
    lock as lock_root,
    lock_file as lock_public_file,
    managed_file_path,
    public_file_path,
    release_token,
    set_locked_files,
    unlock_file as unlock_public_file,
    write as lock_write,
)

from .domain.models import TaskSession


class ManagedDocumentKind(StrEnum):
    """Known managed .agent document kinds."""

    SESSION_STATE = "session_state"
    WORKFLOW_PLAN = "workflow_plan"


class ManagedDocumentOperation(StrEnum):
    """Kinds of managed document writes."""

    DIRECT_WRITE = "direct_write"
    SYSTEM_WRITE = "system_write"


@dataclass(frozen=True)
class ManagedDocumentDecision:
    """One managed document policy decision."""

    decision: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


def managed_document_kind_for_path(relative_path: str) -> ManagedDocumentKind | None:
    """Resolve one managed document kind from a normalized .agent-relative path."""
    if relative_path == DEFAULT_STATE_RELATIVE:
        return ManagedDocumentKind.SESSION_STATE
    if relative_path == DEFAULT_PLAN_RELATIVE:
        return ManagedDocumentKind.WORKFLOW_PLAN
    return None


def _preferred_unmounted_document_path(root_dir: Path, relative_path: str) -> Path:
    managed_target = managed_file_path(root_dir, relative_path)
    public_target = public_file_path(root_dir, relative_path)
    if managed_target.exists() and not public_target.exists():
        return managed_target
    if public_target.exists() and not managed_target.exists():
        return public_target
    if not managed_target.exists() and not public_target.exists():
        return public_target
    if managed_target.stat().st_mtime_ns >= public_target.stat().st_mtime_ns:
        return managed_target
    return public_target


def managed_document_path(root_dir: Path, relative_path: str) -> Path:
    """Return the current readable path for a managed document."""
    if fuse_enabled(root_dir):
        return public_file_path(root_dir, relative_path)
    return _preferred_unmounted_document_path(root_dir, relative_path)


def managed_document_backing_path(root_dir: Path, relative_path: str) -> Path:
    """Return the real backing path for a managed document."""
    if fuse_enabled(root_dir):
        return managed_file_path(root_dir, relative_path)
    return _preferred_unmounted_document_path(root_dir, relative_path)


def _policy_patterns(stage_rule: dict[str, object]) -> tuple[list[str], list[str]]:
    write_policy = stage_rule.get("write_policy", {})
    if not isinstance(write_policy, dict):
        return [], []
    writable_paths = [str(item) for item in write_policy.get("writable_paths", [])]
    denied_paths = [str(item) for item in write_policy.get("denied_paths", [])]
    return writable_paths, denied_paths


def _plan_write_allowed(stage_rule: dict[str, object]) -> bool:
    writable_paths, denied_paths = _policy_patterns(stage_rule)
    if DEFAULT_PLAN_RELATIVE in denied_paths or ".agent/**" in denied_paths:
        return False
    return DEFAULT_PLAN_RELATIVE in writable_paths or ".agent/**" in writable_paths or "**" in writable_paths


class ManagedDocumentPolicyService:
    """Policy service for .agent/state.json and .agent/plan.yaml."""

    def decide_write(
        self,
        session: TaskSession,
        document_kind: ManagedDocumentKind,
        operation: ManagedDocumentOperation,
        *,
        root_dir: Path | None = None,
        stage_rule: dict[str, object] | None = None,
        command_name: str | None = None,
    ) -> ManagedDocumentDecision:
        """Decide whether the managed document may be written."""
        if document_kind == ManagedDocumentKind.SESSION_STATE:
            if operation == ManagedDocumentOperation.DIRECT_WRITE:
                return ManagedDocumentDecision(
                    "block",
                    "Path .agent/state.json is managed by agent-guard and cannot be edited directly. Use agent-guard commands to change task state.",
                )
            return ManagedDocumentDecision("allow", "state.json may be updated by agent-guard.")

        from .workflow_spec import complete_step_allowed_from_stages, stage_spec

        resolved_rule = stage_rule or stage_spec(session.stage, root_dir, session.workflow_id)
        if operation == ManagedDocumentOperation.DIRECT_WRITE:
            if _plan_write_allowed(resolved_rule):
                return ManagedDocumentDecision(
                    "allow",
                    f"Path .agent/plan.yaml is allowed during {session.stage}.",
                )
            return ManagedDocumentDecision(
                "block",
                f"Path .agent/plan.yaml is not writable during {session.stage}.",
            )

        if command_name == "wizard":
            return ManagedDocumentDecision("allow", "plan.yaml may be initialized by the setup wizard.")
        if not session.has_active_task:
            return ManagedDocumentDecision("allow", "plan.yaml may be initialized before a task is active.")
        if command_name == "complete-step" and session.stage in set(
            complete_step_allowed_from_stages(root_dir, session.workflow_id)
        ):
            return ManagedDocumentDecision("allow", f"plan.yaml may be updated by complete-step during {session.stage}.")
        if _plan_write_allowed(resolved_rule):
            return ManagedDocumentDecision(
                "allow",
                f"plan.yaml may be updated by agent-guard during {session.stage}.",
            )
        return ManagedDocumentDecision(
            "block",
            f"plan.yaml cannot be updated by agent-guard during {session.stage}.",
        )


def write_managed_document(
    root_dir: Path,
    relative_path: str,
    content: str,
    *,
    document_kind: ManagedDocumentKind,
    session: TaskSession,
    command_name: str | None = None,
    stage_rule: dict[str, object] | None = None,
) -> Path:
    """Write one managed document through the configured storage path."""
    decision = ManagedDocumentPolicyService().decide_write(
        session,
        document_kind,
        ManagedDocumentOperation.SYSTEM_WRITE,
        root_dir=root_dir,
        stage_rule=stage_rule,
        command_name=command_name,
    )
    if not decision.allowed:
        raise RuntimeError(decision.reason)

    managed_target = managed_file_path(root_dir, relative_path)
    managed_target.parent.mkdir(parents=True, exist_ok=True)
    if fuse_enabled(root_dir):
        public_target = public_file_path(root_dir, relative_path)
        token = lock_root(root_dir)
        try:
            lock_public_file(str(public_target), token)
            lock_write(str(public_target), content, token)
        finally:
            unlock_public_file(str(public_target), token)
            release_token(root_dir, token)
        return public_target

    managed_target.write_text(content, encoding="utf-8")
    public_target = public_file_path(root_dir, relative_path)
    public_target.parent.mkdir(parents=True, exist_ok=True)
    public_target.write_text(content, encoding="utf-8")
    return managed_target


def managed_document_locked_files(root_dir: Path, session: TaskSession) -> list[str]:
    """Return the current strategy-managed locked files for one workspace."""
    files = ["state.json"]
    decision = ManagedDocumentPolicyService().decide_write(
        session,
        ManagedDocumentKind.WORKFLOW_PLAN,
        ManagedDocumentOperation.DIRECT_WRITE,
        root_dir=root_dir,
    )
    if not decision.allowed:
        files.append("plan.yaml")
    return files


def sync_managed_document_protection(root_dir: Path, session: TaskSession) -> list[str]:
    """Persist the current long-lived managed document protection set."""
    return set_locked_files(root_dir, managed_document_locked_files(root_dir, session))
