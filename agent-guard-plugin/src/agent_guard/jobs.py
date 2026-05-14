"""Job state helpers for background work tracking."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .domain.policies import JobPolicyService
from .infrastructure.repositories import JobsRepository
from .state import DEFAULT_JOBS, jobs_path, read_json


def load_jobs(root_dir: Path) -> dict[str, Any]:
    """Load jobs."""
    file_path = jobs_path(root_dir)
    if not file_path.exists():
        return DEFAULT_JOBS.copy()
    return read_json(file_path, "jobs.json")


def check_job_poll(root_dir: Path, job_id: str) -> dict[str, str]:
    """Check job poll."""
    return JobPolicyService(root_dir).check_poll(job_id).to_mapping()
