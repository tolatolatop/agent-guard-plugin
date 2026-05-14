"""Load and normalize the shared workflow specification."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml

from .domain.rules import allowed_rule_names


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
        validate_workflow_spec(data)
        return data
    raise RuntimeError("Could not locate .workflow.yaml.")


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a mapping.")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimeError(f"{label} must be a list.")
    return value


def validate_workflow_spec(spec: dict[str, Any]) -> None:
    """Validate core workflow policy sections and rule names."""
    _require_mapping(spec.get("stages", {}), ".workflow.yaml stages")
    for section_name in ("path_policy", "failure_policy", "finalization_policy", "wizard_defaults"):
        _require_mapping(spec.get(section_name, {}), f".workflow.yaml {section_name}")
    for stage_name, stage_data in workflow_stages_from_spec(spec).items():
        _validate_stage_rules(stage_name, _require_mapping(stage_data, f".workflow.yaml stage {stage_name}"))
    final_rules = _require_list(spec.get("finalization_policy", {}).get("required_rules", []), ".workflow.yaml finalization_policy.required_rules")
    unknown_rules = [str(rule_name) for rule_name in final_rules if str(rule_name) not in allowed_rule_names()]
    if unknown_rules:
        raise RuntimeError(f"Unknown finalization rules in .workflow.yaml: {', '.join(unknown_rules)}")


def workflow_stages_from_spec(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return stages from a provided spec mapping."""
    stages = spec.get("stages", {})
    if not isinstance(stages, dict):
        raise RuntimeError(".workflow.yaml must define a stages mapping.")
    return stages


def _validate_stage_rules(stage_name: str, stage_data: dict[str, Any]) -> None:
    conditions_config = stage_data.get("entry_conditions", {})
    if conditions_config and not isinstance(conditions_config, dict):
        raise RuntimeError(f".workflow.yaml stage {stage_name} entry_conditions must be a mapping.")
    allowed = allowed_rule_names()
    for item in conditions_config.get("any", []) if isinstance(conditions_config, dict) else []:
        if not isinstance(item, dict):
            raise RuntimeError(f".workflow.yaml stage {stage_name} entry_conditions.any item must be a mapping.")
        rule = item.get("rule")
        if rule is None:
            continue
        if str(rule) not in allowed:
            raise RuntimeError(f"Unknown entry condition rule for stage {stage_name}: {rule}")
    write_policy = stage_data.get("write_policy", {})
    if write_policy and not isinstance(write_policy, dict):
        raise RuntimeError(f".workflow.yaml stage {stage_name} write_policy must be a mapping.")
    if isinstance(write_policy, dict):
        _require_list(write_policy.get("writable_paths", []), f".workflow.yaml stage {stage_name} write_policy.writable_paths")
        _require_list(write_policy.get("denied_paths", []), f".workflow.yaml stage {stage_name} write_policy.denied_paths")
    allows_complete_step = stage_data.get("allows_complete_step")
    if allows_complete_step is not None and not isinstance(allows_complete_step, bool):
        raise RuntimeError(f".workflow.yaml stage {stage_name} allows_complete_step must be a boolean.")


def workflow_stages() -> dict[str, dict[str, Any]]:
    """Workflow stages."""
    return workflow_stages_from_spec(load_workflow_spec())


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


def stage_display_artifacts(stage: str) -> list[str]:
    """Artifacts shown in reminders: required first, then extra expected items."""
    required = stage_required_artifacts(stage)
    expected = stage_expected_artifacts(stage)
    seen: set[str] = set()
    merged: list[str] = []
    for artifact in [*required, *expected]:
        if artifact in seen:
            continue
        seen.add(artifact)
        merged.append(artifact)
    return merged


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
    """Generate a Mermaid transition graph from stage transitions."""
    lines = ["flowchart TD"]
    for source, targets in stage_transitions().items():
        for target in targets:
            lines.append(f"  {source} --> {target}")
    return "\n".join(lines)


def global_gates() -> list[str]:
    """Global gates."""
    spec = load_workflow_spec()
    gates = spec.get("global_gates", [])
    if not isinstance(gates, list):
        raise RuntimeError(".workflow.yaml global_gates must be a list.")
    return [str(item) for item in gates]


def protected_paths() -> list[str]:
    """Protected paths."""
    return path_policy()["protected_paths"]


def path_policy() -> dict[str, Any]:
    """Normalized path policy."""
    policy = _require_mapping(load_workflow_spec().get("path_policy", {}), ".workflow.yaml path_policy")
    sensitive_paths = _require_list(policy.get("sensitive_paths", []), ".workflow.yaml path_policy.sensitive_paths")
    protected = _require_list(policy.get("protected_paths", load_workflow_spec().get("protected_paths", [])), ".workflow.yaml path_policy.protected_paths")
    return {
        "sensitive_paths": [str(item) for item in sensitive_paths],
        "protected_paths": [str(item) for item in protected],
    }


def failure_policy() -> dict[str, Any]:
    """Normalized failure policy."""
    policy = _require_mapping(load_workflow_spec().get("failure_policy", {}), ".workflow.yaml failure_policy")
    roots = _require_list(policy.get("fingerprint_roots", ["src", "tests"]), ".workflow.yaml failure_policy.fingerprint_roots")
    return {
        "repeat_threshold": int(policy.get("repeat_threshold", 2)),
        "fingerprint_roots": [str(item) for item in roots],
    }


def finalization_policy() -> dict[str, Any]:
    """Normalized finalization policy."""
    policy = _require_mapping(load_workflow_spec().get("finalization_policy", {}), ".workflow.yaml finalization_policy")
    rule_messages = _require_mapping(policy.get("rule_messages", {}), ".workflow.yaml finalization_policy.rule_messages")
    rules = _require_list(policy.get("required_rules", []), ".workflow.yaml finalization_policy.required_rules")
    return {
        "required_rules": [str(item) for item in rules],
        "rule_messages": {str(key): str(value) for key, value in rule_messages.items()},
    }


def wizard_defaults() -> dict[str, Any]:
    """Normalized wizard defaults."""
    config = _require_mapping(load_workflow_spec().get("wizard_defaults", {}), ".workflow.yaml wizard_defaults")
    return {
        "start_stages": [str(item) for item in _require_list(config.get("start_stages", []), ".workflow.yaml wizard_defaults.start_stages")],
    }


def stage_write_policy(stage: str) -> dict[str, list[str]]:
    """Normalized stage write policy."""
    policy = stage_spec(stage).get("write_policy", {})
    if not isinstance(policy, dict):
        raise RuntimeError(f".workflow.yaml stage {stage} write_policy must be a mapping.")
    writable = _require_list(policy.get("writable_paths", []), f".workflow.yaml stage {stage} write_policy.writable_paths")
    denied = _require_list(policy.get("denied_paths", []), f".workflow.yaml stage {stage} write_policy.denied_paths")
    return {
        "writable_paths": [str(item) for item in writable],
        "denied_paths": [str(item) for item in denied],
    }


def complete_step_allowed_from_stages() -> list[str]:
    """Complete step allowed from stages."""
    return [
        stage_name
        for stage_name, stage_data in workflow_stages().items()
        if stage_data.get("allows_complete_step") is True
    ]
