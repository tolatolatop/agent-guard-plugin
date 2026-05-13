from __future__ import annotations

from pathlib import Path

from .jobs import load_jobs
from .state import load_state
from .workflow_spec import stage_required_artifacts


def can_finalize(root_dir: Path) -> dict[str, object]:
    state = load_state(root_dir)
    jobs = load_jobs(root_dir)
    reasons: list[str] = []

    if state.get("remaining_steps"):
        reasons.append("remaining_steps is not empty")

    if any(job.get("status") == "running" for job in jobs.get("jobs", [])):
        reasons.append("running jobs still exist")

    last_verification = state.get("last_verification")
    if not last_verification or last_verification.get("exit_code") != 0:
        reasons.append("latest final verification is missing or failed")

    if state.get("can_finalize") is not True:
        reasons.append("state.can_finalize is not true")

    required_summary_artifacts = stage_required_artifacts("READY_TO_SUMMARIZE")
    if not all((root_dir / path).exists() for path in required_summary_artifacts):
        reasons.append("required summary artifact is missing")

    if reasons:
        return {"decision": "block", "reasons": reasons}

    return {"decision": "allow", "reasons": []}
