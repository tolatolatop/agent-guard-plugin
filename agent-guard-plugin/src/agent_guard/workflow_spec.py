from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml


def packaged_workflow_path() -> Path:
    return Path(__file__).resolve().parent / ".workflow.yaml"


def source_workflow_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".workflow.yaml"


@lru_cache(maxsize=1)
def load_workflow_spec() -> dict[str, Any]:
    for candidate in (packaged_workflow_path(), source_workflow_path()):
        if not candidate.exists():
            continue
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise RuntimeError(f"Workflow spec must be a YAML mapping: {candidate}")
        return data
    raise RuntimeError("Could not locate .workflow.yaml.")


def workflow_stages() -> dict[str, dict[str, Any]]:
    spec = load_workflow_spec()
    stages = spec.get("stages", {})
    if not isinstance(stages, dict):
        raise RuntimeError(".workflow.yaml must define a stages mapping.")
    return stages


def stage_spec(stage: str) -> dict[str, Any]:
    stages = workflow_stages()
    fallback = stages.get("IDLE", {})
    return stages.get(stage, fallback)


def stage_expected_artifacts(stage: str) -> list[str]:
    artifacts = stage_spec(stage).get("artifacts_expected", [])
    if not isinstance(artifacts, list):
        raise RuntimeError(f".workflow.yaml stage {stage} artifacts_expected must be a list.")
    return [str(item) for item in artifacts]


def stage_required_artifacts(stage: str) -> list[str]:
    artifacts = stage_spec(stage).get("artifacts_required", [])
    if not isinstance(artifacts, list):
        raise RuntimeError(f".workflow.yaml stage {stage} artifacts_required must be a list.")
    return [str(item) for item in artifacts]


def _render_condition_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        referenced_stage = match.group(1)
        artifacts = stage_required_artifacts(referenced_stage)
        if not artifacts:
            return f"{referenced_stage} has no required artifacts"
        if len(artifacts) == 1:
            return artifacts[0]
        return ", ".join(artifacts)

    return re.sub(r"\{required_artifacts:([A-Z_]+)\}", replace, text)


def stage_transition_rules(stage: str) -> dict[str, dict[str, Any]]:
    rules = stage_spec(stage).get("transition_rules", {})
    if not isinstance(rules, dict):
        raise RuntimeError(f".workflow.yaml stage {stage} transition_rules must be a mapping.")
    normalized: dict[str, dict[str, Any]] = {}
    for target_stage, rule in rules.items():
        if not isinstance(rule, dict):
            raise RuntimeError(
                f".workflow.yaml stage {stage} transition_rules for {target_stage} must be a mapping."
            )
        normalized[str(target_stage)] = dict(rule)
    return normalized


def stage_exit_conditions(stage: str) -> dict[str, list[str]]:
    rendered: dict[str, list[str]] = {}
    for target_stage, rule in stage_transition_rules(stage).items():
        raw_conditions = rule.get("display_conditions", [])
        if not isinstance(raw_conditions, list):
            raise RuntimeError(
                f".workflow.yaml stage {stage} transition_rules for {target_stage} display_conditions must be a list."
            )
        rendered[str(target_stage)] = [_render_condition_text(str(item)) for item in raw_conditions]
    return rendered


def stage_transitions() -> dict[str, list[str]]:
    return {
        name: list(stage_data.get("allowed_next_stages", []))
        for name, stage_data in workflow_stages().items()
    }


def transition_graph_mermaid() -> str:
    spec = load_workflow_spec()
    graph = spec.get("transition_graph_mermaid", "")
    return graph.strip() if isinstance(graph, str) else ""


def global_gates() -> list[str]:
    spec = load_workflow_spec()
    gates = spec.get("global_gates", [])
    if not isinstance(gates, list):
        raise RuntimeError(".workflow.yaml global_gates must be a list.")
    return [str(item) for item in gates]


def protected_paths() -> list[str]:
    spec = load_workflow_spec()
    paths = spec.get("protected_paths", [])
    if not isinstance(paths, list):
        raise RuntimeError(".workflow.yaml protected_paths must be a list.")
    return [str(item) for item in paths]


def complete_step_allowed_from_stages() -> list[str]:
    spec = load_workflow_spec()
    command_rules = spec.get("command_rules", {})
    if not isinstance(command_rules, dict):
        raise RuntimeError(".workflow.yaml command_rules must be a mapping.")
    stages = command_rules.get("complete_step_allowed_from_stages", [])
    if not isinstance(stages, list):
        raise RuntimeError(".workflow.yaml command_rules.complete_step_allowed_from_stages must be a list.")
    return [str(item) for item in stages]
