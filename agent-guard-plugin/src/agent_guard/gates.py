from __future__ import annotations

from pathlib import Path

from .jobs import load_jobs
from .plan import load_plan_summary
from .state import AGENT_DIR, load_state


def can_finalize(root_dir: Path) -> dict[str, object]:
    state = load_state(root_dir)
    jobs = load_jobs(root_dir)
    plan = load_plan_summary(root_dir)
    reasons: list[str] = []

    if state.get("remaining_steps"):
        reasons.append("remaining_steps is not empty")

    if any(job.get("status") == "running" for job in jobs.get("jobs", [])):
        reasons.append("running jobs still exist")

    last_verification = state.get("last_verification")
    if not last_verification or last_verification.get("exit_code") != 0:
        reasons.append("latest final verification is missing or failed")

    if plan.get("includesReview"):
        review_path = root_dir / AGENT_DIR / "artifacts" / "review.json"
        if not review_path.exists():
            reasons.append("review artifact is required by plan but missing")

    if state.get("can_finalize") is not True:
        reasons.append("state.can_finalize is not true")

    if reasons:
        return {"decision": "block", "reasons": reasons}

    return {"decision": "allow", "reasons": []}
