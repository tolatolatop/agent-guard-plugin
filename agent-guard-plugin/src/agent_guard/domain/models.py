"""Core domain models for guarded task execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerificationRecord:
    """Recorded verification evidence."""

    command: str
    exit_code: int
    log_path: str | None = None
    recorded_at: str | None = None

    @classmethod
    def from_mapping(cls, payload: "VerificationRecord | dict[str, Any] | None") -> "VerificationRecord | None":
        """Build a verification record from JSON-like state."""
        if not payload:
            return None
        if isinstance(payload, cls):
            return payload
        return cls(
            command=str(payload.get("command", "")),
            exit_code=int(payload.get("exit_code", 0)),
            log_path=str(payload["log_path"]) if payload.get("log_path") is not None else None,
            recorded_at=str(payload["recorded_at"]) if payload.get("recorded_at") is not None else None,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Render to a JSON-serializable mapping."""
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "log_path": self.log_path,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class TaskSession:
    """Aggregate root for one guarded task session."""

    task_id: str | None
    stage: str
    current_step: str | None
    can_finalize: bool = False
    last_verification: VerificationRecord | None = None
    needs_human: bool = False

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "TaskSession":
        """Build a task session from stored state."""
        return cls(
            task_id=str(payload["task_id"]) if payload.get("task_id") is not None else None,
            stage=str(payload["stage"]),
            current_step=str(payload["current_step"]) if payload.get("current_step") is not None else None,
            can_finalize=bool(payload.get("can_finalize", False)),
            last_verification=VerificationRecord.from_mapping(payload.get("last_verification")),
            needs_human=bool(payload.get("needs_human", False)),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Render to the persisted state format."""
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "current_step": self.current_step,
            "can_finalize": self.can_finalize,
            "last_verification": self.last_verification.to_mapping() if self.last_verification else None,
            "needs_human": self.needs_human,
        }

    def start(self, task_id: str, entry_stage: str = "CLARIFYING") -> "TaskSession":
        """Start or resume a task session."""
        next_stage = entry_stage if self.stage == "IDLE" else self.stage
        return self.with_updates(task_id=task_id, stage=next_stage)

    def with_updates(self, **changes: Any) -> "TaskSession":
        """Return a copy with selected updates."""
        payload = self.to_mapping()
        payload.update(changes)
        return TaskSession.from_mapping(payload)

    def advance_to(
        self,
        stage: str,
        current_step: str | None = None,
        can_finalize: bool = False,
    ) -> "TaskSession":
        """Advance the session to another stage."""
        next_can_finalize = can_finalize
        next_needs_human = self.needs_human
        if self.stage in {"NEEDS_FAILURE_ANALYSIS", "NEEDS_HUMAN"} and stage != "NEEDS_HUMAN":
            next_needs_human = False
        if stage == "NEEDS_HUMAN":
            next_needs_human = True
        return TaskSession(
            task_id=self.task_id,
            stage=stage,
            current_step=current_step,
            can_finalize=next_can_finalize,
            last_verification=self.last_verification,
            needs_human=next_needs_human,
        )

    def mark_ready_to_summarize(self, stage: str = "READY_TO_SUMMARIZE") -> "TaskSession":
        """Mark the session ready for final summarization."""
        return self.advance_to(stage, current_step=None, can_finalize=True)

    def mark_done(self, stage: str = "DONE") -> "TaskSession":
        """Mark the session done."""
        return self.advance_to(stage, current_step=None, can_finalize=True)

    def record_verification(self, record: VerificationRecord) -> "TaskSession":
        """Record the latest verification result."""
        return self.with_updates(last_verification=record)

    def enter_failure_analysis(self, stage: str = "NEEDS_FAILURE_ANALYSIS") -> "TaskSession":
        """Escalate the session into failure analysis."""
        return self.advance_to(stage, current_step=self.current_step, can_finalize=False)

    def enter_needs_human(self) -> "TaskSession":
        """Escalate the session for human review."""
        return self.advance_to("NEEDS_HUMAN", current_step=self.current_step, can_finalize=False)

    @property
    def has_active_task(self) -> bool:
        """Return whether a task is active."""
        return bool(self.task_id)


@dataclass(frozen=True)
class PlanStep:
    """A normalized plan step entity."""

    id: str
    goal: str
    status: str
    stage: str | None = None
    commands: list[str] = field(default_factory=list)
    success_condition: str | None = None
    artifacts_required: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, payload: Any, index: int) -> "PlanStep":
        """Normalize a legacy or structured plan step."""
        if not isinstance(payload, dict):
            raise RuntimeError(f"plan.yaml step at index {index} must be a mapping.")
        identifier = payload.get("id", payload.get("name"))
        if not isinstance(identifier, str) or not identifier.strip():
            raise RuntimeError(f"plan.yaml step at index {index} field id/name must be a non-empty string.")
        goal = payload.get("goal", payload.get("description"))
        if not isinstance(goal, str) or not goal.strip():
            raise RuntimeError(f"plan.yaml step at index {index} field goal/description must be a non-empty string.")
        status = payload.get("status")
        if not isinstance(status, str) or not status.strip():
            raise RuntimeError(f"plan.yaml step at index {index} field status must be a non-empty string.")
        commands = payload.get("commands", [])
        if commands is None:
            commands = []
        if not isinstance(commands, list):
            raise RuntimeError(f"plan.yaml step at index {index} field commands must be a list.")
        return cls(
            id=identifier,
            goal=goal,
            status=status,
            stage=str(payload["stage"]) if payload.get("stage") is not None else None,
            commands=[str(item) for item in commands],
            success_condition=str(payload["success_condition"]) if payload.get("success_condition") is not None else None,
            artifacts_required=[str(item) for item in payload.get("artifacts_required", [])],
        )

    def to_mapping(self) -> dict[str, Any]:
        """Render to the richer workflow plan format."""
        payload: dict[str, Any] = {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
        }
        if self.stage:
            payload["stage"] = self.stage
        if self.commands:
            payload["commands"] = list(self.commands)
        if self.success_condition:
            payload["success_condition"] = self.success_condition
        if self.artifacts_required:
            payload["artifacts_required"] = list(self.artifacts_required)
        return payload

    def to_legacy_mapping(self) -> dict[str, str]:
        """Render the compatibility shape used by older call sites."""
        return {
            "name": self.id,
            "description": self.goal,
            "status": self.status,
        }


@dataclass(frozen=True)
class Job:
    """Tracked long-running job entity."""

    id: str
    command: str
    status: str
    started_at: str | None = None
    last_polled_at: str | None = None
    next_poll_after: str | None = None
    poll_count: int = 0
    max_polls: int | None = None
    kind: str | None = None

    @classmethod
    def from_mapping(cls, payload: Any, index: int) -> "Job":
        """Build a job entity from stored JSON."""
        if not isinstance(payload, dict):
            raise RuntimeError(f"jobs.json job at index {index} must be a mapping.")
        job_id = payload.get("id")
        command = payload.get("command")
        status = payload.get("status")
        if not isinstance(job_id, str) or not job_id.strip():
            raise RuntimeError(f"jobs.json job at index {index} field id must be a non-empty string.")
        if not isinstance(command, str) or not command.strip():
            raise RuntimeError(f"jobs.json job at index {index} field command must be a non-empty string.")
        if not isinstance(status, str) or not status.strip():
            raise RuntimeError(f"jobs.json job at index {index} field status must be a non-empty string.")
        return cls(
            id=job_id,
            command=command,
            status=status,
            started_at=str(payload["started_at"]) if payload.get("started_at") is not None else None,
            last_polled_at=str(payload["last_polled_at"]) if payload.get("last_polled_at") is not None else None,
            next_poll_after=str(payload["next_poll_after"]) if payload.get("next_poll_after") is not None else None,
            poll_count=int(payload.get("poll_count", 0) or 0),
            max_polls=int(payload["max_polls"]) if payload.get("max_polls") is not None else None,
            kind=str(payload["kind"]) if payload.get("kind") is not None else None,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Render to stored JSON."""
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "started_at": self.started_at,
            "last_polled_at": self.last_polled_at,
            "next_poll_after": self.next_poll_after,
            "poll_count": self.poll_count,
            "max_polls": self.max_polls,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class FailureRecord:
    """Most recent failure-loop candidate."""

    command: str
    exit_code: int
    failure_hash: str
    repeat_count: int
    code_changed_since_last_failure: bool
    code_fingerprint: int | None = None
    log_path: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "FailureRecord | None":
        """Build a failure record from stored JSON."""
        if not payload:
            return None
        return cls(
            command=str(payload["command"]),
            exit_code=int(payload["exit_code"]),
            failure_hash=str(payload["failure_hash"]),
            repeat_count=int(payload.get("repeat_count", 0)),
            code_changed_since_last_failure=bool(payload.get("code_changed_since_last_failure", False)),
            code_fingerprint=int(payload["code_fingerprint"]) if payload.get("code_fingerprint") is not None else None,
            log_path=str(payload["log_path"]) if payload.get("log_path") is not None else None,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Render to stored JSON."""
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "failure_hash": self.failure_hash,
            "repeat_count": self.repeat_count,
            "code_changed_since_last_failure": self.code_changed_since_last_failure,
            "code_fingerprint": self.code_fingerprint,
            "log_path": self.log_path,
        }


@dataclass(frozen=True)
class GuardDecision:
    """A stable allow/block decision payload."""

    decision: str
    reason: str
    reasons: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_mapping(self) -> dict[str, Any]:
        """Render to CLI JSON."""
        data: dict[str, Any] = {"decision": self.decision, "reason": self.reason}
        if self.reasons:
            data["reasons"] = list(self.reasons)
        data.update(self.payload)
        return data
