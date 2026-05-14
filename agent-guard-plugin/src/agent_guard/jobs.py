"""Job state helpers for background work tracking."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import DEFAULT_JOBS, jobs_path, read_json


def load_jobs(root_dir: Path) -> dict[str, Any]:
    """Load jobs."""
    file_path = jobs_path(root_dir)
    if not file_path.exists():
        return DEFAULT_JOBS.copy()
    return read_json(file_path, "jobs.json")


def check_job_poll(root_dir: Path, job_id: str) -> dict[str, str]:
    """Check job poll."""
    jobs = load_jobs(root_dir)
    job = next((entry for entry in jobs.get("jobs", []) if entry.get("id") == job_id), None)
    if job is None:
        return {"decision": "block", "reason": f"Unknown job id: {job_id}"}

    if job.get("status") != "running":
        return {"decision": "allow", "reason": f"Job {job_id} is already {job.get('status')}."}

    next_poll_after = job.get("next_poll_after")
    if next_poll_after:
        now = datetime.now(timezone.utc)
        if now < datetime.fromisoformat(next_poll_after.replace("Z", "+00:00")):
            return {"decision": "block", "reason": f"Job {job_id} cannot be polled before {next_poll_after}."}

    max_polls = job.get("max_polls")
    poll_count = job.get("poll_count", 0)
    if isinstance(max_polls, int) and poll_count >= max_polls:
        return {
            "decision": "block",
            "reason": f"Job {job_id} exceeded max poll count and requires human review.",
        }

    return {"decision": "allow", "reason": f"Job {job_id} can be polled now."}
