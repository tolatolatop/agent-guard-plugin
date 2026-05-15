"""Load and normalize the shared workflow specification."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml

from .domain.rules import allowed_rule_names


def _workflow_file_error(candidate: Path, detail: str) -> RuntimeError:
    """Build a user-facing workflow-spec corruption error."""
    return RuntimeError(
        f".workflow.yaml appears damaged at {candidate}. {detail} "
        "agent-guard cannot continue until this file is repaired or restored."
    )


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
        try:
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise _workflow_file_error(candidate, f"YAML parsing failed: {exc}.") from exc
        if not isinstance(data, dict):
            raise _workflow_file_error(candidate, "The top-level document must be a YAML mapping.")
        normalized = normalize_workflow_spec(data)
        validate_workflow_spec(normalized)
        return normalized
    raise RuntimeError(
        "Could not locate .workflow.yaml. agent-guard cannot continue until the workflow definition is restored."
    )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a mapping.")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimeError(f"{label} must be a list.")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    return [str(item) for item in _require_list(value, label)]


def _normalize_required_artifact_entry(value: Any, label: str) -> dict[str, str]:
    """Normalize one required-artifact entry from flat or grouped DSL."""
    if isinstance(value, str):
        return {"path": value}
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} item must be a string path or mapping.")
    path = value.get("path")
    if not isinstance(path, str) or not path.strip():
        raise RuntimeError(f"{label} item path must be a non-empty string.")
    normalized = {"path": path}
    matches = value.get("matches")
    if matches is not None:
        if not isinstance(matches, str) or not matches:
            raise RuntimeError(f"{label} item matches must be a non-empty string.")
        normalized["matches"] = matches
    message = value.get("message")
    if message is not None:
        if not isinstance(message, str) or not message.strip():
            raise RuntimeError(f"{label} item message must be a non-empty string.")
        normalized["message"] = message
    return normalized


def _normalize_required_artifacts(value: Any, label: str) -> list[Any]:
    return [_normalize_required_artifact_entry(item, label) for item in _require_list(value, label)]


def _normalize_stage_from_grouped(stage_name: str, stage_data: dict[str, Any]) -> dict[str, Any]:
    intent = _require_mapping(stage_data.get("intent", {}), f".workflow.yaml grouped stage {stage_name} intent")
    permissions = _require_mapping(stage_data.get("permissions", {}), f".workflow.yaml grouped stage {stage_name} permissions")
    transitions = _require_mapping(stage_data.get("transitions", {}), f".workflow.yaml grouped stage {stage_name} transitions")
    evidence = _require_mapping(stage_data.get("evidence", {}), f".workflow.yaml grouped stage {stage_name} evidence")

    write = _require_mapping(permissions.get("write", {}), f".workflow.yaml grouped stage {stage_name} permissions.write")
    actions = _require_mapping(permissions.get("actions", {}), f".workflow.yaml grouped stage {stage_name} permissions.actions")
    commands = _require_mapping(permissions.get("commands", {}), f".workflow.yaml grouped stage {stage_name} permissions.commands")
    handoff = _require_mapping(permissions.get("handoff", {}), f".workflow.yaml grouped stage {stage_name} permissions.handoff")

    complete_step = commands.get("complete_step", "deny")
    if complete_step not in {"allow", "deny"}:
        raise RuntimeError(f".workflow.yaml grouped stage {stage_name} permissions.commands.complete_step must be allow or deny.")

    human_stop = handoff.get("human_stop", "allow")
    if human_stop not in {"allow", "deny"}:
        raise RuntimeError(f".workflow.yaml grouped stage {stage_name} permissions.handoff.human_stop must be allow or deny.")

    normalized: dict[str, Any] = {
        "goal": str(intent.get("goal", "")),
        "allowed_actions": _string_list(actions.get("allow", []), f".workflow.yaml grouped stage {stage_name} permissions.actions.allow"),
        "forbidden_actions": _string_list(actions.get("deny", []), f".workflow.yaml grouped stage {stage_name} permissions.actions.deny"),
        "allowed_next_stages": _string_list(transitions.get("to", []), f".workflow.yaml grouped stage {stage_name} transitions.to"),
        "entry_conditions": {
            "any": _require_list(transitions.get("enter_when", []), f".workflow.yaml grouped stage {stage_name} transitions.enter_when"),
        },
        "artifacts_expected": _string_list(evidence.get("expected", []), f".workflow.yaml grouped stage {stage_name} evidence.expected"),
        "artifacts_required": _normalize_required_artifacts(evidence.get("required", []), f".workflow.yaml grouped stage {stage_name} evidence.required"),
        "write_policy": {
            "writable_paths": _string_list(write.get("allow", []), f".workflow.yaml grouped stage {stage_name} permissions.write.allow"),
            "denied_paths": _string_list(write.get("deny", []), f".workflow.yaml grouped stage {stage_name} permissions.write.deny"),
        },
    }
    if complete_step == "allow":
        normalized["allows_complete_step"] = True
    if human_stop == "deny":
        normalized["forbid_needs_human"] = {
            "display": str(
                handoff.get(
                    "deny_message",
                    "Current stage does not allow human intervention; continue advancing the task.",
                )
            )
        }
    return normalized


def normalize_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalize either the flat workflow format or the grouped DSL format."""
    if "globals" not in spec:
        return spec

    globals_config = _require_mapping(spec.get("globals", {}), ".workflow.yaml globals")
    workflow_config = _require_mapping(
        spec.get("workflow", spec.get("metadata", {})),
        ".workflow.yaml workflow",
    )
    paths = _require_mapping(globals_config.get("paths", {}), ".workflow.yaml globals.paths")
    failures = _require_mapping(globals_config.get("failures", {}), ".workflow.yaml globals.failures")
    finalization = _require_mapping(globals_config.get("finalization", {}), ".workflow.yaml globals.finalization")
    wizard = _require_mapping(globals_config.get("wizard", {}), ".workflow.yaml globals.wizard")
    session_start = _require_mapping(globals_config.get("session_start", {}), ".workflow.yaml globals.session_start")
    install = _require_mapping(globals_config.get("install", {}), ".workflow.yaml globals.install")
    install_skills = _require_mapping(install.get("skills", {}), ".workflow.yaml globals.install.skills")
    grouped_stages = _require_mapping(spec.get("stages", {}), ".workflow.yaml stages")

    return {
        "version": spec.get("version", 1),
        "metadata": {
            "id": str(workflow_config.get("id", "")),
            "title": str(workflow_config.get("title", "")),
            "description": str(workflow_config.get("description", "")),
        },
        "global_gates": _string_list(spec.get("global_gates", []), ".workflow.yaml global_gates"),
        "protected_paths": _string_list(paths.get("protected", []), ".workflow.yaml globals.paths.protected"),
        "path_policy": {
            "protected_paths": _string_list(paths.get("protected", []), ".workflow.yaml globals.paths.protected"),
            "sensitive_paths": _string_list(paths.get("sensitive", []), ".workflow.yaml globals.paths.sensitive"),
        },
        "failure_policy": {
            "repeat_threshold": int(failures.get("repeat_threshold", 2)),
            "fingerprint_roots": _string_list(failures.get("fingerprint_roots", ["src", "tests"]), ".workflow.yaml globals.failures.fingerprint_roots"),
        },
        "finalization_policy": {
            "required_rules": _string_list(finalization.get("require", []), ".workflow.yaml globals.finalization.require"),
            "rule_messages": {
                str(key): str(value)
                for key, value in _require_mapping(finalization.get("messages", {}), ".workflow.yaml globals.finalization.messages").items()
            },
        },
        "wizard_defaults": {
            "start_stages": _string_list(wizard.get("start_stages", []), ".workflow.yaml globals.wizard.start_stages"),
        },
        "session_start_defaults": {
            "navigator_skill": str(session_start.get("navigator_skill", "using-workflow")),
        },
        "install_defaults": {
            "skill_match": _string_list(install_skills.get("match", []), ".workflow.yaml globals.install.skills.match"),
            "skill_exclude_match": _string_list(
                install_skills.get("exclude_match", []),
                ".workflow.yaml globals.install.skills.exclude_match",
            ),
        },
        "stages": {
            stage_name: _normalize_stage_from_grouped(stage_name, _require_mapping(stage_data, f".workflow.yaml stage {stage_name}"))
            for stage_name, stage_data in grouped_stages.items()
        },
    }


def validate_workflow_spec(spec: dict[str, Any]) -> None:
    """Validate core workflow policy sections and rule names."""
    _require_mapping(spec.get("stages", {}), ".workflow.yaml stages")
    for section_name in ("path_policy", "failure_policy", "finalization_policy", "wizard_defaults", "session_start_defaults", "install_defaults"):
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
    _require_list(stage_data.get("artifacts_expected", []), f".workflow.yaml stage {stage_name} artifacts_expected")
    _normalize_required_artifacts(stage_data.get("artifacts_required", []), f".workflow.yaml stage {stage_name} artifacts_required")
    allows_complete_step = stage_data.get("allows_complete_step")
    if allows_complete_step is not None and not isinstance(allows_complete_step, bool):
        raise RuntimeError(f".workflow.yaml stage {stage_name} allows_complete_step must be a boolean.")


def workflow_stages() -> dict[str, dict[str, Any]]:
    """Workflow stages."""
    return workflow_stages_from_spec(load_workflow_spec())


def workflow_metadata() -> dict[str, str]:
    """Normalized workflow metadata."""
    metadata = _require_mapping(load_workflow_spec().get("metadata", {}), ".workflow.yaml metadata")
    return {
        "id": str(metadata.get("id", "")),
        "title": str(metadata.get("title", "")),
        "description": str(metadata.get("description", "")),
    }


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
    return [entry["path"] for entry in stage_required_artifact_rules(stage)]


def stage_required_artifact_rules(stage: str) -> list[dict[str, str]]:
    """Normalized required artifact rules for one stage."""
    artifacts = stage_spec(stage).get("artifacts_required", [])
    if not isinstance(artifacts, list):
        raise RuntimeError(f".workflow.yaml stage {stage} artifacts_required must be a list.")
    return [
        _normalize_required_artifact_entry(item, f".workflow.yaml stage {stage} artifacts_required")
        for item in artifacts
    ]


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


def stage_intent(stage: str) -> dict[str, str]:
    """Grouped DSL intent view for one stage."""
    return {
        "goal": str(stage_spec(stage).get("goal", "")),
    }


def stage_permissions(stage: str) -> dict[str, Any]:
    """Grouped DSL permissions view for one stage."""
    rules = stage_spec(stage)
    handoff = {"human_stop": "allow"}
    deny_message = stage_forbid_needs_human_display(stage)
    if deny_message is not None:
        handoff = {
            "human_stop": "deny",
            "deny_message": deny_message,
        }
    return {
        "write": {
            "allow": stage_write_policy(stage)["writable_paths"],
            "deny": stage_write_policy(stage)["denied_paths"],
        },
        "actions": {
            "allow": [str(item) for item in rules.get("allowed_actions", [])],
            "deny": [str(item) for item in rules.get("forbidden_actions", [])],
        },
        "commands": {
            "complete_step": "allow" if stage in complete_step_allowed_from_stages() else "deny",
        },
        "handoff": handoff,
    }


def stage_transition_policy(stage: str) -> dict[str, Any]:
    """Grouped DSL transition view for one stage."""
    return {
        "to": stage_transitions().get(stage, []),
        "enter_when": stage_entry_conditions(stage),
    }


def stage_evidence(stage: str) -> dict[str, list[str]]:
    """Grouped DSL evidence view for one stage."""
    return {
        "expected": stage_expected_artifacts(stage),
        "required": stage_required_artifacts(stage),
        "display": stage_display_artifacts(stage),
    }


def stage_policy_view(stage: str) -> dict[str, Any]:
    """Grouped DSL stage view assembled from the current flat workflow format."""
    return {
        "intent": stage_intent(stage),
        "permissions": stage_permissions(stage),
        "transitions": stage_transition_policy(stage),
        "evidence": stage_evidence(stage),
    }


def stage_policy_roles(stage: str) -> dict[str, Any]:
    """Role annotations for the grouped DSL stage view."""
    permissions = stage_permissions(stage)
    return {
        "intent": "soft_prompt",
        "permissions": {
            "write": "hard_gate",
            "actions": "soft_prompt",
            "commands": "hard_gate",
            "handoff": "hard_gate" if permissions["handoff"]["human_stop"] == "deny" else "soft_prompt",
        },
        "transitions": "hard_gate",
        "evidence": {
            "expected": "soft_prompt",
            "required": "hard_gate",
            "display": "projection",
        },
    }


def workflow_policy_view() -> dict[str, Any]:
    """Grouped DSL workflow view assembled from the current flat workflow format."""
    return {
        "workflow": workflow_metadata(),
        "globals": {
            "paths": {
                "protected": path_policy()["protected_paths"],
                "sensitive": path_policy()["sensitive_paths"],
            },
            "failures": failure_policy(),
            "finalization": {
                "require": finalization_policy()["required_rules"],
                "messages": finalization_policy()["rule_messages"],
            },
            "wizard": wizard_defaults(),
            "session_start": {
                "navigator_skill": session_start_defaults()["navigator_skill"],
            },
            "install": {
                "skills": {
                    "match": install_defaults()["skill_match"],
                    "exclude_match": install_defaults()["skill_exclude_match"],
                }
            },
        },
        "stages": {
            stage_name: stage_policy_view(stage_name)
            for stage_name in workflow_stages()
        },
    }


def workflow_policy_roles() -> dict[str, Any]:
    """Role annotations for the grouped workflow DSL."""
    return {
        "workflow": "soft_prompt",
        "globals": {
            "paths": "hard_gate",
            "failures": "hard_gate",
            "finalization": "hard_gate",
            "wizard": "soft_prompt",
            "session_start": "soft_prompt",
            "install": "soft_prompt",
        },
        "stages": {
            stage_name: stage_policy_roles(stage_name)
            for stage_name in workflow_stages()
        },
    }


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


def install_defaults() -> dict[str, list[str]]:
    """Normalized install defaults."""
    config = _require_mapping(load_workflow_spec().get("install_defaults", {}), ".workflow.yaml install_defaults")
    return {
        "skill_match": [str(item) for item in _require_list(config.get("skill_match", []), ".workflow.yaml install_defaults.skill_match")],
        "skill_exclude_match": [
            str(item) for item in _require_list(config.get("skill_exclude_match", []), ".workflow.yaml install_defaults.skill_exclude_match")
        ],
    }


def session_start_defaults() -> dict[str, Any]:
    """Normalized session-start prompt defaults."""
    config = _require_mapping(load_workflow_spec().get("session_start_defaults", {}), ".workflow.yaml session_start_defaults")
    skill_id = str(config.get("navigator_skill", "")).strip()
    if not skill_id:
        raise RuntimeError(".workflow.yaml session_start_defaults.navigator_skill must be a non-empty string.")
    return {
        "navigator_skill": skill_id,
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
