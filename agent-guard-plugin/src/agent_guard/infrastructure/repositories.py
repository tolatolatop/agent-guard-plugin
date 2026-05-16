"""Repositories for .agent workspace persistence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from agent_guard_file_lock import (
    DEFAULT_PLAN_RELATIVE,
    fuse_enabled,
    lock as lock_file,
    lock_file as lock_public_file,
    managed_file_path,
    public_file_path,
    unlock_file as unlock_public_file,
    unlock as unlock_file,
    write as lock_write,
)

from ..domain.models import FailureRecord, Job, PlanStep, TaskSession
from ..state import (
    DEFAULT_FAILURES,
    DEFAULT_JOBS,
    events_path,
    failures_path,
    jobs_path,
    load_task_session,
    read_json,
    save_task_session,
)


class StateRepository:
    """Repository for task session state."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def load(self) -> TaskSession:
        """Load the task session aggregate."""
        return load_task_session(self.root_dir)

    def save(self, session: TaskSession) -> TaskSession:
        """Persist the task session aggregate."""
        return save_task_session(self.root_dir, session)


class PlanRepository:
    """Repository for workflow plans."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.file_path = self.root_dir / ".agent" / "plan.yaml"

    def load_raw(self) -> dict[str, Any] | None:
        """Load raw YAML plan data."""
        if fuse_enabled(self.root_dir):
            actual_path = public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
        else:
            managed_target = managed_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
            actual_path = (
                managed_target
                if managed_target.exists()
                else public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
            )
        if not actual_path.exists():
            return None
        try:
            data = yaml.safe_load(actual_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"plan.yaml is invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("plan.yaml must contain a YAML mapping.")
        steps = data.get("steps", [])
        if steps is None:
            data["steps"] = []
        elif not isinstance(steps, list):
            raise RuntimeError("plan.yaml steps must be a list.")
        return data

    def load_steps(self) -> list[PlanStep]:
        """Load normalized plan steps."""
        data = self.load_raw()
        if data is None:
            return []
        return [PlanStep.from_mapping(step, index) for index, step in enumerate(data.get("steps", []))]

    def save_steps(self, task_id: str | None, steps: list[PlanStep]) -> dict[str, Any]:
        """Persist a structured plan document."""
        payload = {
            "task_id": task_id,
            "steps": [step.to_mapping() for step in steps],
        }
        rendered = yaml.safe_dump(payload, sort_keys=False)
        managed_target = managed_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
        managed_target.parent.mkdir(parents=True, exist_ok=True)
        if fuse_enabled(self.root_dir):
            token = lock_file(self.root_dir)
            try:
                lock_public_file(str(public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)), token)
                lock_write(str(public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)), rendered, token)
            finally:
                unlock_public_file(str(public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)), token)
                unlock_file(self.root_dir, token)
        else:
            managed_target.write_text(rendered, encoding="utf-8")
            public_target = public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
            public_target.parent.mkdir(parents=True, exist_ok=True)
            public_target.write_text(rendered, encoding="utf-8")
        return payload

    def update_step_status(self, step_id: str, status: str) -> dict[str, Any]:
        """Update one step by stable id/name."""
        data = self.load_raw()
        if data is None:
            raise RuntimeError("plan.yaml does not exist.")
        updated = False
        for index, step in enumerate(data.get("steps", [])):
            normalized = PlanStep.from_mapping(step, index)
            if normalized.id != step_id:
                continue
            step["status"] = status
            updated = True
            break
        if not updated:
            raise RuntimeError(f"plan.yaml step {step_id} was not found.")
        rendered = yaml.safe_dump(data, sort_keys=False)
        managed_target = managed_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
        managed_target.parent.mkdir(parents=True, exist_ok=True)
        if fuse_enabled(self.root_dir):
            token = lock_file(self.root_dir)
            try:
                lock_public_file(str(public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)), token)
                lock_write(str(public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)), rendered, token)
            finally:
                unlock_public_file(str(public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)), token)
                unlock_file(self.root_dir, token)
        else:
            managed_target.write_text(rendered, encoding="utf-8")
            public_target = public_file_path(self.root_dir, DEFAULT_PLAN_RELATIVE)
            public_target.parent.mkdir(parents=True, exist_ok=True)
            public_target.write_text(rendered, encoding="utf-8")
        return data


class JobsRepository:
    """Repository for tracked jobs."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def load_raw(self) -> dict[str, Any]:
        """Load raw jobs JSON."""
        file_path = jobs_path(self.root_dir)
        if not file_path.exists():
            return DEFAULT_JOBS.copy()
        return read_json(file_path, "jobs.json")

    def load_jobs(self) -> list[Job]:
        """Load validated jobs."""
        return [Job.from_mapping(entry, index) for index, entry in enumerate(self.load_raw().get("jobs", []))]


class FailuresRepository:
    """Repository for failure-loop state."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def load(self) -> FailureRecord | None:
        """Load the last failure record."""
        file_path = failures_path(self.root_dir)
        if not file_path.exists():
            return FailureRecord.from_mapping(DEFAULT_FAILURES["last_failure"])
        payload = read_json(file_path, "failures.json")
        return FailureRecord.from_mapping(payload.get("last_failure"))

    def save(self, failure: FailureRecord | None) -> FailureRecord | None:
        """Persist the last failure record."""
        failures_path(self.root_dir).write_text(
            json.dumps({"last_failure": failure.to_mapping() if failure else None}, indent=2) + "\n",
            encoding="utf-8",
        )
        return failure


class EventsRepository:
    """Repository for append-only event logs."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a JSONL event."""
        file_path = events_path(self.root_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        return payload
