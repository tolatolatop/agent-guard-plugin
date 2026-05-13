from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .transitions import (
    STAGE_TRANSITIONS,
    automatic_transitions,
    transition_conditions_for_stage,
    transition_graph_lines,
    workflow_commands,
)

GLOBAL_GATES = [
    "Do not write outside allowed_paths.",
    "Do not retry identical failing commands without code changes or failure analysis.",
    "Do not claim completion unless can-finalize passes.",
]

STAGE_RULES = {
    "IDLE": {
        "goal": "Load task state and determine the next concrete step.",
        "allowed_actions": ["read .agent state", "inspect plan and job files", "start-task when task_id is unset"],
        "forbidden_actions": ["claim work is complete", "skip state initialization"],
    },
    "CLARIFYING": {
        "goal": "Resolve task intent, assumptions, and missing inputs before implementation.",
        "allowed_actions": ["clarify requirements", "inspect repository state", "capture unresolved risks"],
        "forbidden_actions": ["start implementation before requirements are clear"],
    },
    "DESIGNING": {
        "goal": "Write the smallest design needed to guide implementation safely.",
        "allowed_actions": ["draft a design note", "identify artifacts and validation steps"],
        "forbidden_actions": ["broad implementation before the design is settled"],
    },
    "PLANNING": {
        "goal": "Break work into explicit steps with success conditions and path scope.",
        "allowed_actions": ["write or refine plan.yaml", "set allowed and forbidden paths per step"],
        "forbidden_actions": ["execute unplanned broad changes"],
    },
    "RED_TEST": {
        "goal": "Create a failing test that proves the missing behavior.",
        "allowed_actions": ["write tests", "run targeted tests", "save failing logs"],
        "forbidden_actions": ["write production code", "claim implementation is complete"],
    },
    "GREEN_IMPL": {
        "goal": "Implement the smallest code change that makes the targeted test pass.",
        "allowed_actions": ["write minimal production code", "update tests if required", "run targeted verification"],
        "forbidden_actions": ["broad refactors", "unrelated formatting", "dependency upgrades unless planned"],
    },
    "REVIEW": {
        "goal": "Review the diff and capture review evidence without changing code.",
        "allowed_actions": ["read diff", "read files", "write review artifact"],
        "forbidden_actions": ["modify source unless review findings create a new implementation step"],
    },
    "VERIFY": {
        "goal": "Run verification commands and record final evidence.",
        "allowed_actions": ["run verification commands", "write verification logs"],
        "forbidden_actions": ["new implementation work unless the state moves to NEEDS_FAILURE_ANALYSIS"],
    },
    "READY_TO_SUMMARIZE": {
        "goal": "Summarize completed work and verification results without further edits.",
        "allowed_actions": ["summarize work", "list changed files", "report verification commands and results"],
        "forbidden_actions": ["further code changes"],
    },
    "NEEDS_FAILURE_ANALYSIS": {
        "goal": "Stop retry loops and produce evidence-backed failure analysis before changing code again.",
        "allowed_actions": ["inspect logs", "write failure-analysis.md", "identify minimal fix and next verification command"],
        "forbidden_actions": ["rerun the same failing command without analysis", "continue source edits without evidence"],
    },
    "NEEDS_HUMAN": {
        "goal": "Escalate blocked or risky work for human review.",
        "allowed_actions": ["report blocker", "request approval", "pause risky actions"],
        "forbidden_actions": ["continue sensitive or ambiguous work without approval"],
    },
    "DONE": {
        "goal": "Task is complete; preserve state and await the next task.",
        "allowed_actions": ["report completion evidence", "wait for next instruction"],
        "forbidden_actions": ["resume editing under the completed task"],
    },
}

def _parse_skill_metadata(file_path: Path, skill_id: str) -> dict[str, str]:
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
    if not base_dir.exists():
        return []
    discovered: dict[str, dict[str, str]] = {}

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
    return STAGE_RULES.get(stage, STAGE_RULES["IDLE"])


def get_workflow_context(root_dir: Path, stage: str) -> dict[str, Any]:
    rules = get_stage_rules(stage)
    base_dir = (
        Path(os.environ["AGENT_GUARD_SKILLS_DIR"])
        if os.environ.get("AGENT_GUARD_SKILLS_DIR")
        else Path(__file__).resolve().parents[2] / "docs" / "skills"
    )
    skill_catalog = discover_skills(base_dir)
    return {
        "current_stage_goal": rules["goal"],
        "allowed_actions": rules["allowed_actions"],
        "forbidden_actions": rules["forbidden_actions"],
        "transitions_in": [source for source, targets in STAGE_TRANSITIONS.items() if stage in targets],
        "transitions_out": STAGE_TRANSITIONS.get(stage, []),
        "transition_conditions": transition_conditions_for_stage(stage),
        "transition_graph": transition_graph_lines(),
        "workflow_commands": workflow_commands(),
        "automatic_transitions": automatic_transitions(),
        "global_gates": GLOBAL_GATES,
        "skill_catalog": skill_catalog,
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
    skill_paths = ", ".join(skill["absolute_path"] for skill in workflow_context["skill_catalog"])
    transitions_out = ", ".join(workflow_context["transitions_out"]) or "none"
    transition_conditions = " | ".join(
        f"{target}: {', '.join(conditions)}"
        for target, conditions in workflow_context["transition_conditions"].items()
    ) or "none"
    transition_graph = " | ".join(workflow_context["transition_graph"])
    command_help = " | ".join(workflow_context["workflow_commands"])
    automatic_moves = " | ".join(workflow_context["automatic_transitions"])
    allowed = "; ".join(workflow_context["allowed_actions"])
    forbidden = "; ".join(workflow_context["forbidden_actions"])
    gates = "; ".join(workflow_context["global_gates"])
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
        f"Transition graph: {transition_graph}\n"
        f"Workflow commands: {command_help}\n"
        f"Automatic transitions: {automatic_moves}\n"
        f"Consult skills in this order: {skill_paths}"
        f"{archive_line}"
    )
