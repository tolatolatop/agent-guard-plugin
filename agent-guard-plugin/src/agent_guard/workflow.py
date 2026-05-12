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

SKILL_CATALOG = [
    {
        "id": "workflow-navigator",
        "title": "Workflow Navigator",
        "path": "docs/skills/workflow-navigator.md",
        "purpose": "Top-level navigation skill that tells the model how to choose the next workflow skill.",
        "trigger_when": "Always consult first at session start and whenever the current step is unclear.",
    },
    {
        "id": "workflow-core",
        "title": "Core Workflow",
        "path": "docs/skills/workflow-core.md",
        "purpose": "Canonical workflow stages, transitions, and guard expectations.",
        "trigger_when": "Use when deciding what stage comes next or what actions are legal in the current stage.",
    },
    {
        "id": "failure-analysis",
        "title": "Failure Analysis",
        "path": "docs/skills/failure-analysis.md",
        "purpose": "Evidence-first handling for repeated failures and blocked verification.",
        "trigger_when": "Use when stage is NEEDS_FAILURE_ANALYSIS or the same command failed repeatedly.",
    },
    {
        "id": "finalization-checklist",
        "title": "Finalization Checklist",
        "path": "docs/skills/finalization-checklist.md",
        "purpose": "Rules for review artifacts, verification evidence, and safe completion.",
        "trigger_when": "Use before summarizing, finalizing, or reporting completion.",
    },
]


def skill_absolute_path(base_dir: Path, skill: dict[str, str]) -> Path:
    if base_dir.name == "skills" and base_dir.parent.name == ".claude":
        return base_dir / skill["id"] / "SKILL.md"
    return base_dir / Path(skill["path"]).name


def get_stage_rules(stage: str) -> dict[str, Any]:
    return STAGE_RULES.get(stage, STAGE_RULES["IDLE"])


def get_workflow_context(root_dir: Path, stage: str) -> dict[str, Any]:
    rules = get_stage_rules(stage)
    base_dir = Path(os.environ["AGENT_GUARD_SKILLS_DIR"]) if os.environ.get("AGENT_GUARD_SKILLS_DIR") else root_dir / "docs" / "skills"
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
        "skill_catalog": [
            {**skill, "absolute_path": str(skill_absolute_path(base_dir, skill))}
            for skill in SKILL_CATALOG
        ],
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
