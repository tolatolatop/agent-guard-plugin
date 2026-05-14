"""Workflow prompt construction and skill discovery helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .install import packaged_skills_dir
from .transitions import (
    STAGE_TRANSITIONS,
    transition_conditions_for_stage,
)
from .workflow_spec import (
    complete_step_allowed_from_stages,
    global_gates,
    stage_expected_artifacts,
    stage_required_artifacts,
    stage_spec,
    transition_graph_mermaid,
)

def _parse_skill_metadata(file_path: Path, skill_id: str) -> dict[str, str]:
    """Internal helper for parse skill metadata."""
    fallback_title = skill_id.replace("-", " ").replace("_", " ").title()
    metadata = {
        "title": fallback_title,
        "description": "",
    }
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].strip() == "---":
            for line in lines[1:]:
                stripped = line.strip()
                if stripped == "---":
                    break
                if ":" not in stripped:
                    continue
                key, value = stripped.split(":", 1)
                normalized_key = key.strip().lower()
                normalized_value = value.strip()
                if normalized_key == "name" and normalized_value:
                    metadata["title"] = normalized_value
                elif normalized_key == "description" and normalized_value:
                    metadata["description"] = normalized_value
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                metadata["title"] = metadata["title"] or stripped[2:].strip()
                if metadata["title"] == fallback_title:
                    metadata["title"] = stripped[2:].strip()
                break
    except OSError:
        return metadata
    return metadata


def discover_skills(base_dir: Path) -> list[dict[str, str]]:
    """Discover skills."""
    if not base_dir.exists():
        return []
    discovered: dict[str, dict[str, str]] = {}

    # Support both the repo's flat markdown skills and Claude-style bundled
    # skills directories so session-start can describe whichever install layout
    # is active.
    for file_path in sorted(base_dir.glob("*.md")):
        skill_id = file_path.stem
        discovered[skill_id] = {
            "id": skill_id,
            **_parse_skill_metadata(file_path, skill_id),
            "path": f"docs/skills/{skill_id}.md",
            "absolute_path": str(file_path),
        }

    for skill_dir in sorted(path for path in base_dir.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        skill_id = skill_dir.name
        discovered[skill_id] = {
            "id": skill_id,
            **_parse_skill_metadata(skill_file, skill_id),
            "path": f"docs/skills/{skill_id}.md",
            "absolute_path": str(skill_file),
        }

    return [discovered[skill_id] for skill_id in sorted(discovered)]


def get_stage_rules(stage: str) -> dict[str, Any]:
    """Return stage rules."""
    return stage_spec(stage)


def _read_skill_body(file_path: Path) -> str:
    """Internal helper for read skill body."""
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[index + 1 :]).strip()
    return text.strip()


def get_workflow_context(root_dir: Path, stage: str) -> dict[str, Any]:
    """Return workflow context."""
    rules = get_stage_rules(stage)
    base_dir = (
        Path(os.environ["AGENT_GUARD_SKILLS_DIR"])
        if os.environ.get("AGENT_GUARD_SKILLS_DIR")
        else packaged_skills_dir()
    )
    skill_catalog = discover_skills(base_dir)
    using_workflow_skill = next(
        (skill for skill in skill_catalog if skill.get("id") == "using-workflow"),
        None,
    )
    # This dictionary is the single payload used by session-start and related
    # reminders, so it keeps prompt generation and machine-readable state aligned.
    return {
        "current_stage_goal": rules["goal"],
        "allowed_actions": rules.get("allowed_actions", []),
        "forbidden_actions": rules.get("forbidden_actions", []),
        "stage_allowed_paths": rules.get("allowed_paths", []),
        "stage_forbidden_paths": rules.get("forbidden_paths", []),
        "stage_expected_artifacts": stage_expected_artifacts(stage),
        "stage_required_artifacts": stage_required_artifacts(stage),
        "stage_writable": rules.get("writable"),
        "transitions_in": [source for source, targets in STAGE_TRANSITIONS.items() if stage in targets],
        "transitions_out": STAGE_TRANSITIONS.get(stage, []),
        "transition_conditions": transition_conditions_for_stage(stage),
        "transition_graph_mermaid": transition_graph_mermaid(),
        "complete_step_allowed_from_stages": complete_step_allowed_from_stages(),
        "global_gates": global_gates(),
        "skill_catalog": skill_catalog,
        "using_workflow_skill_body": _read_skill_body(Path(using_workflow_skill["absolute_path"])) if using_workflow_skill else "",
    }


def build_session_prompt_block(
    task_id: str | None,
    stage: str,
    current_step: str | None,
    next_step: str | None,
    allowed_paths: list[str],
    forbidden_paths: list[str],
    can_finalize: bool,
    workflow_context: dict[str, Any],
    recent_archive: dict[str, Any] | None = None,
) -> str:
    """Build session prompt block."""
    transitions_out = ", ".join(workflow_context["transitions_out"]) or "none"
    transition_conditions = " | ".join(
        f"{target}: {', '.join(conditions)}"
        for target, conditions in workflow_context["transition_conditions"].items()
    ) or "none"
    allowed = "; ".join(workflow_context["allowed_actions"])
    forbidden = "; ".join(workflow_context["forbidden_actions"])
    gates = "; ".join(workflow_context["global_gates"])
    stage_allowed_paths = workflow_context["stage_allowed_paths"] or ["<none>"]
    stage_forbidden_paths = workflow_context["stage_forbidden_paths"] or ["<none>"]
    stage_expected_artifacts = workflow_context["stage_expected_artifacts"] or ["<none>"]
    stage_required_artifacts = workflow_context["stage_required_artifacts"] or ["<none>"]
    stage_writable = workflow_context["stage_writable"]
    transition_graph = workflow_context["transition_graph_mermaid"]
    complete_step_allowed = workflow_context["complete_step_allowed_from_stages"] or ["<none>"]
    using_workflow_skill_body = workflow_context["using_workflow_skill_body"]
    archive_line = ""
    if recent_archive:
        archive_line = (
            f"\nLast archived task: {recent_archive.get('archived_task_id') or 'unknown'} "
            f"at {recent_archive.get('archive_dir')}"
        )
    return (
        "AGENT-GUARD NAVIGATOR\n"
        f"Task: {task_id or 'unset'}\n"
        f"Stage: {stage}\n"
        f"Current step: {current_step or 'unset'}\n"
        f"Next required action: {next_step or 'none'}\n"
        f"Allowed paths: {allowed_paths or ['<any>']}\n"
        f"Forbidden paths: {forbidden_paths or ['<none>']}\n"
        f"Can finalize: {can_finalize}\n"
        f"Stage goal: {workflow_context['current_stage_goal']}\n"
        f"Stage exits: {transitions_out}\n"
        f"Stage exit conditions: {transition_conditions}\n"
        f"Allowed actions: {allowed}\n"
        f"Forbidden actions: {forbidden}\n"
        f"Global gates: {gates}\n"
        "Transition graph (mermaid):\n"
        "```mermaid\n"
        f"{transition_graph}\n"
        "```\n"
        + (f"Stage writable mode: {stage_writable}\n" if stage_writable else "")
        + f"Stage allowed paths: {stage_allowed_paths}\n"
        + f"Stage forbidden paths: {stage_forbidden_paths}\n"
        + f"Stage expected artifacts: {stage_expected_artifacts}\n"
        + f"Stage required artifacts: {stage_required_artifacts}\n"
        + f"Complete-step allowed from: {complete_step_allowed}\n"
        "Using Workflow skill:\n"
        f"{using_workflow_skill_body}"
        f"{archive_line}"
    )
