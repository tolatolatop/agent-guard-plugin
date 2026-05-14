"""Load and normalize the shared workflow specification."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml


def packaged_workflow_path() -> Path:
    """Packaged workflow path."""
    return Path(__file__).resolve().parent / ".workflow.yaml"


def source_workflow_path() -> Path:
    """Source workflow path."""
    return Path(__file__).resolve().parents[2] / ".workflow.yaml"


@lru_cache(maxsize=1)
def load_workflow_spec() -> dict[str, Any]:
    # Prefer the installed copy first so the runtime behavior matches the
    # packaged tool, while still allowing source-tree execution in tests.
    """Load workflow spec."""
    for candidate in (packaged_workflow_path(), source_workflow_path()):
        if not candidate.exists():
            continue
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise RuntimeError(f"Workflow spec must be a YAML mapping: {candidate}")
        return data
    raise RuntimeError("Could not locate .workflow.yaml.")


def workflow_stages() -> dict[str, dict[str, Any]]:
    """Workflow stages."""
    spec = load_workflow_spec()
    stages = spec.get("stages", {})
    if not isinstance(stages, dict):
        raise RuntimeError(".workflow.yaml must define a stages mapping.")
    return stages


def stage_spec(stage: str) -> dict[str, Any]:
    """Stage spec."""
    stages = workflow_stages()
    fallback = stages.get("IDLE", {})
    return stages.get(stage, fallback)


def stage_expected_artifacts(stage: str) -> list[str]:
    """Stage expected artifacts."""
    artifacts = stage_spec(stage).get("artifacts_expected", [])
    if not isinstance(artifacts, list):
        raise RuntimeError(f".workflow.yaml stage {stage} artifacts_expected must be a list.")
    return [str(item) for item in artifacts]


def stage_required_artifacts(stage: str) -> list[str]:
    """Stage required artifacts."""
    artifacts = stage_spec(stage).get("artifacts_required", [])
    if not isinstance(artifacts, list):
        raise RuntimeError(f".workflow.yaml stage {stage} artifacts_required must be a list.")
    return [str(item) for item in artifacts]


def _render_condition_text(text: str) -> str:
    # Exit-condition display strings can reference another stage's required
    # artifacts so the prompt stays in sync with the single workflow source.
    """Internal helper for render condition text."""
    def replace(match: re.Match[str]) -> str:
        """Replace."""
        referenced_stage = match.group(1)
        artifacts = stage_required_artifacts(referenced_stage)
        if not artifacts:
            return f"{referenced_stage} has no required artifacts"
        if len(artifacts) == 1:
            return artifacts[0]
        return ", ".join(artifacts)

    return re.sub(r"\{required_artifacts:([A-Z_]+)\}", replace, text)


def _normalize_entry_condition(stage: str, item: Any, label: str) -> dict[str, str]:
    """Internal helper for normalize entry condition."""
    if not isinstance(item, dict):
        raise RuntimeError(f".workflow.yaml stage {stage} {label} condition must be a mapping.")
    display = item.get("display")
    if not isinstance(display, str) or not display.strip():
        raise RuntimeError(f".workflow.yaml stage {stage} {label} condition display must be a non-empty string.")
    normalized = {"display": _render_condition_text(display)}
    rule = item.get("rule")
    if rule is not None:
        normalized["rule"] = str(rule)
    value = item.get("value")
    if value is not None:
        normalized["value"] = str(value)
    return normalized


def stage_entry_conditions(stage: str, from_stage: str | None = None) -> list[dict[str, str]]:
    """Stage entry conditions."""
    rules = stage_spec(stage)
    conditions_config = rules.get("entry_conditions", {})
    if conditions_config and not isinstance(conditions_config, dict):
        raise RuntimeError(f".workflow.yaml stage {stage} entry_conditions must be a mapping.")

    normalized: list[dict[str, str]] = []
    any_conditions = conditions_config.get("any", []) if isinstance(conditions_config, dict) else []
    if any_conditions and not isinstance(any_conditions, list):
        raise RuntimeError(f".workflow.yaml stage {stage} entry_conditions.any must be a list.")
    for item in any_conditions:
        normalized.append(_normalize_entry_condition(stage, item, "entry_conditions.any"))
    return normalized


def stage_forbid_needs_human_display(stage: str) -> str | None:
    # This stage-level flag is used by the Stop hook to block final responses
    # until the task advances out of stages that should stay agent-driven.
    """Stage forbid needs human display."""
    needs_human_rule = stage_spec(stage).get("forbid_needs_human")
    if not needs_human_rule:
        return None
    if isinstance(needs_human_rule, dict):
        display = needs_human_rule.get("display")
        if not isinstance(display, str) or not display.strip():
            raise RuntimeError(f".workflow.yaml stage {stage} forbid_needs_human.display must be a non-empty string.")
        return display
    if needs_human_rule is True:
        return "Current stage does not allow human intervention; continue advancing the task."
    raise RuntimeError(f".workflow.yaml stage {stage} forbid_needs_human must be true or a mapping.")


def stage_exit_conditions(stage: str) -> dict[str, list[str]]:
    """Stage exit conditions."""
    rendered: dict[str, list[str]] = {}
    # Leaving a stage depends on its own required artifacts plus the
    # destination stage's entry conditions.
    artifact_conditions = [f"{path} must exist" for path in stage_required_artifacts(stage)]
    for target_stage in stage_transitions().get(stage, []):
        entry_conditions = [condition["display"] for condition in stage_entry_conditions(target_stage, stage)]
        rendered[str(target_stage)] = artifact_conditions + entry_conditions
    return rendered


def stage_transitions() -> dict[str, list[str]]:
    """Stage transitions."""
    return {
        name: list(stage_data.get("allowed_next_stages", []))
        for name, stage_data in workflow_stages().items()
    }


def transition_graph_mermaid() -> str:
    """Transition graph mermaid."""
    spec = load_workflow_spec()
    graph = spec.get("transition_graph_mermaid", "")
    return graph.strip() if isinstance(graph, str) else ""


def global_gates() -> list[str]:
    """Global gates."""
    spec = load_workflow_spec()
    gates = spec.get("global_gates", [])
    if not isinstance(gates, list):
        raise RuntimeError(".workflow.yaml global_gates must be a list.")
    return [str(item) for item in gates]


def protected_paths() -> list[str]:
    """Protected paths."""
    spec = load_workflow_spec()
    paths = spec.get("protected_paths", [])
    if not isinstance(paths, list):
        raise RuntimeError(".workflow.yaml protected_paths must be a list.")
    return [str(item) for item in paths]


def complete_step_allowed_from_stages() -> list[str]:
    """Complete step allowed from stages."""
    spec = load_workflow_spec()
    command_rules = spec.get("command_rules", {})
    if not isinstance(command_rules, dict):
        raise RuntimeError(".workflow.yaml command_rules must be a mapping.")
    stages = command_rules.get("complete_step_allowed_from_stages", [])
    if not isinstance(stages, list):
        raise RuntimeError(".workflow.yaml command_rules.complete_step_allowed_from_stages must be a list.")
    return [str(item) for item in stages]
