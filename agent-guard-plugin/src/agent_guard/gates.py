from __future__ import annotations

from pathlib import Path

from .jobs import load_jobs
from .plan import load_plan, nonterminal_plan_steps
from .state import load_state


def can_finalize(root_dir: Path) -> dict[str, object]:
    # Finalization is intentionally lightweight: no running jobs, the workflow
    # has explicitly enabled finalization, and any plan steps are terminal.
    state = load_state(root_dir)
    jobs = load_jobs(root_dir)
    reasons: list[str] = []

    if any(job.get("status") == "running" for job in jobs.get("jobs", [])):
        reasons.append("running jobs still exist")

    if state.get("can_finalize") is not True:
        reasons.append("state.can_finalize is not true")

    if load_plan(root_dir) is not None:
        nonterminal_steps = nonterminal_plan_steps(root_dir)
        if nonterminal_steps:
            names = ", ".join(step["name"] for step in nonterminal_steps)
            reasons.append(f"plan.yaml has non-terminal steps: {names}")

    if reasons:
        return {"decision": "block", "reasons": reasons}

    return {"decision": "allow", "reasons": []}
