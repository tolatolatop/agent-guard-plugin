"""Workflow prompt construction and skill discovery helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .install import packaged_skills_dir
from .transitions import (
    transition_conditions_for_stage,
)
from .workflow_spec import (
    complete_step_allowed_from_stages,
    global_gates,
    session_start_defaults,
    stage_policy_view,
    stage_transitions,
    transition_graph_mermaid,
    workflow_metadata,
    workflow_policy_roles,
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
                if normalized_key == "name" and normalized_value and normalized_value != skill_id:
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


def get_stage_rules(stage: str, root_dir: Path | None = None, workflow_id: str | None = None) -> dict[str, Any]:
    """Return stage rules."""
    return stage_policy_view(stage, root_dir, workflow_id)


def _read_skill_body(file_path: Path) -> str:
    """Internal helper for read skill body."""
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[index + 1 :]).strip()
    return text.strip()


def resolve_session_start_navigator(skill_catalog: list[dict[str, str]], root_dir: Path | None = None, workflow_id: str | None = None) -> dict[str, str]:
    """Resolve the configured navigator skill from the discovered catalog."""
    skill_id = session_start_defaults(root_dir, workflow_id)["navigator_skill"]
    navigator_skill = next(
        (skill for skill in skill_catalog if skill.get("id") == skill_id),
        None,
    )
    if navigator_skill is None and skill_catalog:
        navigator_skill = skill_catalog[0]
    if navigator_skill is None:
        return {
            "skill_id": skill_id,
            "name": "Using Workflow",
            "instruction": "Consult this navigator first, then load specialist workflow skills on demand.",
            "prompt_heading": "Workflow Navigator",
            "path": None,
            "absolute_path": None,
            "body": "",
        }
    return {
        "skill_id": navigator_skill["id"],
        "name": navigator_skill.get("title") or "Using Workflow",
        "instruction": "Consult this navigator first, then load specialist workflow skills on demand.",
        "prompt_heading": "Workflow Navigator",
        "path": navigator_skill["path"],
        "absolute_path": navigator_skill["absolute_path"],
        "body": _read_skill_body(Path(navigator_skill["absolute_path"])),
    }


def get_workflow_context(root_dir: Path, stage: str, workflow_id: str | None = None) -> dict[str, Any]:
    """Return workflow context."""
    rules = stage_policy_view(stage, root_dir, workflow_id)
    base_dir = (
        Path(os.environ["AGENT_GUARD_SKILLS_DIR"])
        if os.environ.get("AGENT_GUARD_SKILLS_DIR")
        else packaged_skills_dir()
    )
    skill_catalog = discover_skills(base_dir)
    navigator = resolve_session_start_navigator(skill_catalog, root_dir, workflow_id)
    transitions = transition_graph_mermaid(root_dir, workflow_id)
    stage_map = stage_transitions(root_dir, workflow_id)
    # This dictionary is the single payload used by session-start and related
    # reminders, so it keeps prompt generation and machine-readable state aligned.
    return {
        "workflow_metadata": workflow_metadata(root_dir, workflow_id),
        "policy_roles": workflow_policy_roles(root_dir, workflow_id),
        "stage_policy": rules,
        "soft_prompt": {
            "goal": rules["intent"]["goal"],
            "allowed_actions": rules["permissions"]["actions"]["allow"],
            "forbidden_actions": rules["permissions"]["actions"]["deny"],
            "expected_artifacts": rules["evidence"]["expected"],
        },
        "hard_gates": {
            "write_allow": rules["permissions"]["write"]["allow"],
            "write_deny": rules["permissions"]["write"]["deny"],
            "required_artifacts": rules["evidence"]["required"],
            "transition_targets": stage_map.get(stage, []),
            "transition_conditions": transition_conditions_for_stage(stage, root_dir, workflow_id),
            "complete_step": rules["permissions"]["commands"]["complete_step"],
            "global_gates": global_gates(root_dir, workflow_id),
        },
        "current_stage_goal": rules["intent"]["goal"],
        "allowed_actions": rules["permissions"]["actions"]["allow"],
        "forbidden_actions": rules["permissions"]["actions"]["deny"],
        "stage_writable_paths": rules["permissions"]["write"]["allow"],
        "stage_denied_paths": rules["permissions"]["write"]["deny"],
        "stage_display_artifacts": rules["evidence"]["display"],
        "stage_expected_artifacts": rules["evidence"]["expected"],
        "stage_required_artifacts": rules["evidence"]["required"],
        "transitions_in": [source for source, targets in stage_map.items() if stage in targets],
        "transitions_out": stage_map.get(stage, []),
        "transition_conditions": transition_conditions_for_stage(stage, root_dir, workflow_id),
        "transition_graph_mermaid": transitions,
        "complete_step_allowed_from_stages": complete_step_allowed_from_stages(root_dir, workflow_id),
        "global_gates": global_gates(root_dir, workflow_id),
        "skill_catalog": skill_catalog,
        "session_start_navigator": navigator,
    }


def build_session_prompt_block(
    task_id: str | None,
    stage: str,
    current_step: str | None,
    next_step: str | None,
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
    stage_writable_paths = workflow_context["stage_writable_paths"] or ["<none>"]
    stage_denied_paths = workflow_context["stage_denied_paths"] or ["<none>"]
    stage_display_artifacts = workflow_context["stage_display_artifacts"] or ["<none>"]
    stage_expected_artifacts = workflow_context["stage_expected_artifacts"] or ["<none>"]
    stage_required_artifacts = workflow_context["stage_required_artifacts"] or ["<none>"]
    transition_graph = workflow_context["transition_graph_mermaid"]
    complete_step_allowed = workflow_context["complete_step_allowed_from_stages"] or ["<none>"]
    navigator = workflow_context["session_start_navigator"]
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
        f"Can finalize: {can_finalize}\n"
        "Soft guidance:\n"
        f"Stage goal: {workflow_context['current_stage_goal']}\n"
        f"Allowed actions: {allowed}\n"
        f"Forbidden actions: {forbidden}\n"
        f"Stage expected artifacts: {stage_expected_artifacts}\n"
        "Hard gates:\n"
        f"Stage exits: {transitions_out}\n"
        f"Stage exit conditions: {transition_conditions}\n"
        f"Global gates: {gates}\n"
        "Transition graph (mermaid):\n"
        "```mermaid\n"
        f"{transition_graph}\n"
        "```\n"
        + f"Stage writable paths: {stage_writable_paths}\n"
        + f"Stage denied paths: {stage_denied_paths}\n"
        + f"Stage artifacts: {stage_display_artifacts}\n"
        + f"Stage required artifacts: {stage_required_artifacts}\n"
        + f"Complete-step allowed from: {complete_step_allowed}\n"
        + f"{navigator['prompt_heading']}:\n"
        + f"{navigator['body']}"
        f"{archive_line}"
    )
