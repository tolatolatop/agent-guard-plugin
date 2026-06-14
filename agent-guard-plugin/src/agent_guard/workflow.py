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
    failure_policy,
    finalization_policy,
    global_gates,
    install_defaults,
    path_policy,
    session_start_defaults,
    stage_entry_conditions,
    stage_exit_conditions,
    stage_plan_mode,
    stage_policy_view,
    stage_transitions,
    transition_graph_mermaid,
    workflow_metadata,
    workflow_entry_stage,
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
    globals_guidance = global_gates(root_dir, workflow_id)
    paths = path_policy(root_dir, workflow_id)
    finalize = finalization_policy(root_dir, workflow_id)
    failures = failure_policy(root_dir, workflow_id)
    install = install_defaults(root_dir, workflow_id)
    guidance = {
        "goal": rules["intent"]["goal"],
        "allowed_actions": rules["permissions"]["actions"]["allow"],
        "forbidden_actions": rules["permissions"]["actions"]["deny"],
        "expected_artifacts": rules["evidence"]["expected"],
        "display_artifacts": rules["evidence"]["display"],
        "global_guidance": globals_guidance,
    }
    gates = {
        "required_artifacts": rules["evidence"]["required"],
        "enter": stage_entry_conditions(stage, None, root_dir, workflow_id),
        "exit": stage_exit_conditions(stage, root_dir, workflow_id),
        "finalization": {
            "required_rules": finalize["required_rules"],
            "messages": finalize["rule_messages"],
        },
        "failure": {
            "repeat_threshold": failures["repeat_threshold"],
            "fingerprint_roots": failures["fingerprint_roots"],
        },
    }
    write_policy = {
        "allow": rules["permissions"]["write"]["allow"],
        "deny": rules["permissions"]["write"]["deny"],
        "protected": paths["protected_paths"],
        "sensitive": paths["sensitive_paths"],
    }
    flow = {
        "entry": workflow_entry_stage(root_dir, workflow_id),
        "current": stage,
        "next": stage_map.get(stage, []),
        "inbound": [source for source, targets in stage_map.items() if stage in targets],
        "graph": stage_map,
        "graph_mermaid": transitions,
        "transition_conditions": transition_conditions_for_stage(stage, root_dir, workflow_id),
    }
    plan = {
        "mode": stage_plan_mode(stage, root_dir, workflow_id),
        "complete_step_allowed": stage in complete_step_allowed_from_stages(root_dir, workflow_id),
        "complete_step_allowed_from_stages": complete_step_allowed_from_stages(root_dir, workflow_id),
    }
    context = {
        "session_start_navigator": navigator,
        "skill_catalog": skill_catalog,
        "install_defaults": {
            "skills": {
                "match": install["skill_match"],
                "exclude_match": install["skill_exclude_match"],
            }
        },
    }
    # This dictionary is the session-start contract. It separates soft prompt
    # guidance from hard gates and write policy so callers do not infer runtime
    # behavior from display-only fields such as expect or allow.actions.
    return {
        "workflow_metadata": workflow_metadata(root_dir, workflow_id),
        "guidance": guidance,
        "gates": gates,
        "write_policy": write_policy,
        "flow": flow,
        "plan": plan,
        "context": context,
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
    transitions_out = ", ".join(workflow_context["flow"]["next"]) or "none"
    transition_conditions = " | ".join(
        f"{target}: {', '.join(conditions)}"
        for target, conditions in workflow_context["flow"]["transition_conditions"].items()
    ) or "none"
    allowed = "; ".join(workflow_context["guidance"]["allowed_actions"])
    forbidden = "; ".join(workflow_context["guidance"]["forbidden_actions"])
    guidance = "; ".join(workflow_context["guidance"]["global_guidance"])
    stage_writable_paths = workflow_context["write_policy"]["allow"] or ["<none>"]
    stage_denied_paths = workflow_context["write_policy"]["deny"] or ["<none>"]
    stage_display_artifacts = workflow_context["guidance"]["display_artifacts"] or ["<none>"]
    stage_expected_artifacts = workflow_context["guidance"]["expected_artifacts"] or ["<none>"]
    stage_required_artifacts = workflow_context["gates"]["required_artifacts"] or ["<none>"]
    transition_graph = workflow_context["flow"]["graph_mermaid"]
    complete_step_allowed = workflow_context["plan"]["complete_step_allowed_from_stages"] or ["<none>"]
    navigator = workflow_context["context"]["session_start_navigator"]
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
        f"Stage goal: {workflow_context['guidance']['goal']}\n"
        f"Allowed actions: {allowed}\n"
        f"Forbidden actions: {forbidden}\n"
        f"Global guidance: {guidance}\n"
        f"Stage expected artifacts: {stage_expected_artifacts}\n"
        f"Stage display artifacts: {stage_display_artifacts}\n"
        "Hard gates:\n"
        f"Stage exits: {transitions_out}\n"
        f"Stage exit conditions: {transition_conditions}\n"
        "Transition graph (mermaid):\n"
        "```mermaid\n"
        f"{transition_graph}\n"
        "```\n"
        + f"Stage writable paths: {stage_writable_paths}\n"
        + f"Stage denied paths: {stage_denied_paths}\n"
        + f"Stage required artifacts: {stage_required_artifacts}\n"
        + f"Complete-step allowed from: {complete_step_allowed}\n"
        + f"{navigator['prompt_heading']}:\n"
        + f"{navigator['body']}"
        f"{archive_line}"
    )
