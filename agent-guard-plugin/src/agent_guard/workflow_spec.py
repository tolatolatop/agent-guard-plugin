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


def _normalize_canonical_check_item(value: Any, label: str) -> str | dict[str, str]:
    """Normalize one canonical check item."""
    if isinstance(value, str):
        if not value.strip():
            raise RuntimeError(f"{label} item must be a non-empty string.")
        return value
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} item must be a string or mapping.")
    if "path" in value:
        return _normalize_required_artifact_entry(value, label)
    if "rule" in value:
        rule = value.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            raise RuntimeError(f"{label} item rule must be a non-empty string.")
        normalized = {"rule": rule}
        mapped_value = value.get("value")
        if mapped_value is not None:
            normalized["value"] = str(mapped_value)
        display = value.get("display")
        if display is not None:
            if not isinstance(display, str) or not display.strip():
                raise RuntimeError(f"{label} item display must be a non-empty string.")
            normalized["display"] = display
        return normalized
    if "display" in value:
        display = value.get("display")
        if not isinstance(display, str) or not display.strip():
            raise RuntimeError(f"{label} item display must be a non-empty string.")
        return {"display": display}
    raise RuntimeError(f"{label} item must define either path or rule.")


def _normalize_canonical_check_items(value: Any, label: str) -> list[str | dict[str, str]]:
    return [_normalize_canonical_check_item(item, label) for item in _require_list(value, label)]


def _legacy_plan_mode(stage_name: str) -> str:
    """Map legacy coding-oriented stages to the canonical plan mode."""
    if stage_name == "PLANNING":
        return "create"
    if stage_name in {"READY_TO_SUMMARIZE", "DONE"}:
        return "complete"
    if stage_name in {"RED_TEST", "GREEN_IMPL", "REVIEW", "VERIFY", "NEEDS_FAILURE_ANALYSIS"}:
        return "advance" if stage_name in {"RED_TEST", "GREEN_IMPL", "REVIEW", "VERIFY"} else "follow"
    return "deny"


def _legacy_stop_allowed(stage_name: str) -> bool:
    """Compatibility stop behavior for the current grouped workflow."""
    return stage_name in {"IDLE", "CLARIFYING", "PLANNING", "NEEDS_HUMAN", "DONE"}


def _apply_plan_path_policy(plan_mode: str, writable_paths: list[str], denied_paths: list[str]) -> tuple[list[str], list[str]]:
    """Bind .agent/plan.yaml write access to the stage plan mode."""
    normalized_writable = [str(item) for item in writable_paths if str(item) != ".agent/plan.yaml"]
    normalized_denied = [str(item) for item in denied_paths if str(item) != ".agent/plan.yaml"]
    if plan_mode == "create":
        if ".agent/plan.yaml" not in normalized_writable:
            normalized_writable = [*normalized_writable, ".agent/plan.yaml"]
        return normalized_writable, normalized_denied
    if ".agent/**" not in normalized_denied and ".agent/plan.yaml" not in normalized_denied:
        normalized_denied = [*normalized_denied, ".agent/plan.yaml"]
    return normalized_writable, normalized_denied


def _apply_plan_artifact_defaults(
    plan_mode: str,
    expected_artifacts: list[str],
    required_artifacts: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    """Bind plan-related artifact expectations to the stage plan mode."""
    normalized_expected = [str(item) for item in expected_artifacts if str(item) != ".agent/plan.yaml"]
    normalized_required = [dict(item) for item in required_artifacts if item.get("path") != ".agent/plan.yaml"]
    if plan_mode == "create":
        return [*normalized_expected, ".agent/plan.yaml"], [*normalized_required, {"path": ".agent/plan.yaml"}]
    return normalized_expected, normalized_required


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

    plan_mode = _legacy_plan_mode(stage_name)
    writable_paths, denied_paths = _apply_plan_path_policy(
        plan_mode,
        _string_list(write.get("allow", []), f".workflow.yaml grouped stage {stage_name} permissions.write.allow"),
        _string_list(write.get("deny", []), f".workflow.yaml grouped stage {stage_name} permissions.write.deny"),
    )

    expected_artifacts, required_artifacts = _apply_plan_artifact_defaults(
        plan_mode,
        _string_list(evidence.get("expected", []), f".workflow.yaml grouped stage {stage_name} evidence.expected"),
        _normalize_required_artifacts(evidence.get("required", []), f".workflow.yaml grouped stage {stage_name} evidence.required"),
    )

    normalized: dict[str, Any] = {
        "goal": str(intent.get("goal", "")),
        "allowed_actions": _string_list(actions.get("allow", []), f".workflow.yaml grouped stage {stage_name} permissions.actions.allow"),
        "forbidden_actions": _string_list(actions.get("deny", []), f".workflow.yaml grouped stage {stage_name} permissions.actions.deny"),
        "allowed_next_stages": _string_list(transitions.get("to", []), f".workflow.yaml grouped stage {stage_name} transitions.to"),
        "entry_conditions": {
            "any": _require_list(transitions.get("enter_when", []), f".workflow.yaml grouped stage {stage_name} transitions.enter_when"),
        },
        "artifacts_expected": expected_artifacts,
        "artifacts_required": required_artifacts,
        "write_policy": {
            "writable_paths": writable_paths,
            "denied_paths": denied_paths,
        },
        "plan_mode": plan_mode,
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


def _normalize_entry_condition_from_canonical(stage_name: str, value: Any) -> dict[str, str]:
    """Normalize one canonical enter-condition item into the flat internal form."""
    item = _normalize_canonical_check_item(value, f".workflow.yaml canonical stage {stage_name} enter")
    if isinstance(item, str):
        return {"display": item}
    if "path" in item:
        return {"display": f"{item['path']} must exist"}
    if "rule" in item:
        normalized = {"display": str(item.get("display") or item["rule"]), "rule": item["rule"]}
        mapped_value = item.get("value")
        if mapped_value is not None:
            normalized["value"] = str(mapped_value)
        return normalized
    if "display" in item:
        return {"display": item["display"]}
    raise RuntimeError(f".workflow.yaml canonical stage {stage_name} enter item must define a displayable condition.")


def _normalize_stage_from_canonical(stage_name: str, stage_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize one canonical stage into the flat internal workflow format."""
    allow = _require_mapping(stage_data.get("allow", {}), f".workflow.yaml canonical stage {stage_name} allow")
    deny = _require_mapping(stage_data.get("deny", {}), f".workflow.yaml canonical stage {stage_name} deny")
    plan_mode = str(stage_data.get("plan", "deny"))
    writable_paths, denied_paths = _apply_plan_path_policy(
        plan_mode,
        _string_list(allow.get("write", []), f".workflow.yaml canonical stage {stage_name} allow.write"),
        _string_list(deny.get("write", []), f".workflow.yaml canonical stage {stage_name} deny.write"),
    )

    expected_artifacts, required_artifacts = _apply_plan_artifact_defaults(
        plan_mode,
        _string_list(stage_data.get("expect", []), f".workflow.yaml canonical stage {stage_name} expect"),
        [
            _normalize_required_artifact_entry(item, f".workflow.yaml canonical stage {stage_name} exit")
            for item in _require_list(stage_data.get("exit", []), f".workflow.yaml canonical stage {stage_name} exit")
        ],
    )

    normalized: dict[str, Any] = {
        "goal": str(stage_data.get("goal", "")),
        "allowed_actions": _string_list(allow.get("actions", []), f".workflow.yaml canonical stage {stage_name} allow.actions"),
        "forbidden_actions": _string_list(deny.get("actions", []), f".workflow.yaml canonical stage {stage_name} deny.actions"),
        "allowed_next_stages": _string_list(stage_data.get("next", []), f".workflow.yaml canonical stage {stage_name} next"),
        "entry_conditions": {
            "any": [
                _normalize_entry_condition_from_canonical(stage_name, item)
                for item in _require_list(stage_data.get("enter", []), f".workflow.yaml canonical stage {stage_name} enter")
            ],
        },
        "artifacts_expected": expected_artifacts,
        "artifacts_required": required_artifacts,
        "write_policy": {
            "writable_paths": writable_paths,
            "denied_paths": denied_paths,
        },
        "plan_mode": plan_mode,
    }
    if str(stage_data.get("plan", "deny")) == "advance":
        normalized["allows_complete_step"] = True
    if bool(stage_data.get("final", False)):
        normalized["is_final_stage"] = True
    if allow.get("human") is False:
        normalized["forbid_needs_human"] = {
            "display": "Current stage does not allow human intervention; continue advancing the task."
        }
    return normalized


def _is_canonical_workflow_dsl(spec: dict[str, Any], globals_config: dict[str, Any]) -> bool:
    """Detect whether the input workflow document already uses the new author DSL."""
    if "protected" in globals_config or "sensitive" in globals_config or "finalize" in globals_config:
        return True
    stages = spec.get("stages", {})
    if isinstance(stages, dict):
        for stage_data in stages.values():
            if isinstance(stage_data, dict) and (
                "goal" in stage_data
                or "plan" in stage_data
                or "allow" in stage_data
                or "deny" in stage_data
                or "enter" in stage_data
                or "exit" in stage_data
                or "next" in stage_data
                or "final" in stage_data
            ):
                return True
    return False


def normalize_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalize either the flat workflow format or the grouped DSL format."""
    if "globals" not in spec:
        return spec

    globals_config = _require_mapping(spec.get("globals", {}), ".workflow.yaml globals")
    workflow_config = _require_mapping(
        spec.get("workflow", spec.get("metadata", {})),
        ".workflow.yaml workflow",
    )
    stages = _require_mapping(spec.get("stages", {}), ".workflow.yaml stages")

    if _is_canonical_workflow_dsl(spec, globals_config):
        failures = _require_mapping(globals_config.get("failures", {}), ".workflow.yaml globals.failures")
        finalize = _require_mapping(globals_config.get("finalize", {}), ".workflow.yaml globals.finalize")
        wizard = _require_mapping(globals_config.get("wizard", {}), ".workflow.yaml globals.wizard")
        session_start = _require_mapping(globals_config.get("session_start", {}), ".workflow.yaml globals.session_start")
        install = _require_mapping(globals_config.get("install", {}), ".workflow.yaml globals.install")
        install_skills = _require_mapping(install.get("skills", {}), ".workflow.yaml globals.install.skills")
        workflow_entry = str(workflow_config.get("entry", "IDLE"))

        finalize_require = _require_list(finalize.get("require", []), ".workflow.yaml globals.finalize.require")
        normalized_finalize_rules: list[str] = []
        for item in finalize_require:
            normalized_item = _normalize_canonical_check_item(item, ".workflow.yaml globals.finalize.require")
            if isinstance(normalized_item, str):
                normalized_finalize_rules.append(normalized_item)
                continue
            rule = normalized_item.get("rule")
            if not rule:
                raise RuntimeError(".workflow.yaml globals.finalize.require item must resolve to a rule.")
            normalized_finalize_rules.append(str(rule))

        return {
            "version": spec.get("version", 2),
            "metadata": {
                "id": str(workflow_config.get("id", "")),
                "title": str(workflow_config.get("title", "")),
                "description": str(workflow_config.get("description", "")),
                "entry": workflow_entry,
            },
            "entry_stage": workflow_entry,
            "global_gates": _string_list(spec.get("global_gates", []), ".workflow.yaml global_gates"),
            "protected_paths": _string_list(globals_config.get("protected", []), ".workflow.yaml globals.protected"),
            "path_policy": {
                "protected_paths": _string_list(globals_config.get("protected", []), ".workflow.yaml globals.protected"),
                "sensitive_paths": _string_list(globals_config.get("sensitive", []), ".workflow.yaml globals.sensitive"),
            },
            "failure_policy": {
                "repeat_threshold": int(failures.get("repeat_threshold", 2)),
                "fingerprint_roots": _string_list(
                    failures.get("fingerprint_roots", ["src", "tests"]),
                    ".workflow.yaml globals.failures.fingerprint_roots",
                ),
            },
            "finalization_policy": {
                "required_rules": normalized_finalize_rules,
                "rule_messages": {
                    str(key): str(value)
                    for key, value in _require_mapping(finalize.get("messages", {}), ".workflow.yaml globals.finalize.messages").items()
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
                stage_name: _normalize_stage_from_canonical(
                    stage_name,
                    _require_mapping(stage_data, f".workflow.yaml stage {stage_name}"),
                )
                for stage_name, stage_data in stages.items()
            },
        }

    paths = _require_mapping(globals_config.get("paths", {}), ".workflow.yaml globals.paths")
    failures = _require_mapping(globals_config.get("failures", {}), ".workflow.yaml globals.failures")
    finalization = _require_mapping(globals_config.get("finalization", {}), ".workflow.yaml globals.finalization")
    wizard = _require_mapping(globals_config.get("wizard", {}), ".workflow.yaml globals.wizard")
    session_start = _require_mapping(globals_config.get("session_start", {}), ".workflow.yaml globals.session_start")
    install = _require_mapping(globals_config.get("install", {}), ".workflow.yaml globals.install")
    install_skills = _require_mapping(install.get("skills", {}), ".workflow.yaml globals.install.skills")

    return {
        "version": spec.get("version", 1),
        "metadata": {
            "id": str(workflow_config.get("id", "")),
            "title": str(workflow_config.get("title", "")),
            "description": str(workflow_config.get("description", "")),
            "entry": str(workflow_config.get("entry", "")),
        },
        "entry_stage": str(workflow_config.get("entry", "")),
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
            for stage_name, stage_data in stages.items()
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


def validate_canonical_workflow_spec(spec: dict[str, Any]) -> None:
    """Validate the projected canonical workflow model."""
    workflow = _require_mapping(spec.get("workflow", {}), ".workflow.yaml canonical workflow")
    stages = _require_mapping(spec.get("stages", {}), ".workflow.yaml canonical stages")
    entry = workflow.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        raise RuntimeError(".workflow.yaml canonical workflow.entry must be a non-empty string.")
    if entry not in stages:
        raise RuntimeError(f".workflow.yaml canonical workflow.entry references unknown stage: {entry}")

    globals_config = _require_mapping(spec.get("globals", {}), ".workflow.yaml canonical globals")
    finalize = _require_mapping(globals_config.get("finalize", {}), ".workflow.yaml canonical globals.finalize")
    for item in _normalize_canonical_check_items(finalize.get("require", []), ".workflow.yaml canonical globals.finalize.require"):
        if isinstance(item, dict) and item.get("rule") and item["rule"] not in allowed_rule_names():
            raise RuntimeError(f"Unknown finalization rules in .workflow.yaml: {item['rule']}")

    allowed_plan_modes = {"deny", "create", "follow", "advance", "complete"}
    for stage_name, raw_stage in stages.items():
        stage_data = _require_mapping(raw_stage, f".workflow.yaml canonical stage {stage_name}")
        if str(stage_data.get("plan", "deny")) not in allowed_plan_modes:
            raise RuntimeError(
                f".workflow.yaml canonical stage {stage_name} plan must be one of: deny, create, follow, complete."
            )
        allow = _require_mapping(stage_data.get("allow", {}), f".workflow.yaml canonical stage {stage_name} allow")
        deny = _require_mapping(stage_data.get("deny", {}), f".workflow.yaml canonical stage {stage_name} deny")
        _require_list(allow.get("write", []), f".workflow.yaml canonical stage {stage_name} allow.write")
        _require_list(allow.get("actions", []), f".workflow.yaml canonical stage {stage_name} allow.actions")
        _require_list(deny.get("write", []), f".workflow.yaml canonical stage {stage_name} deny.write")
        _require_list(deny.get("actions", []), f".workflow.yaml canonical stage {stage_name} deny.actions")
        _normalize_canonical_check_items(stage_data.get("enter", []), f".workflow.yaml canonical stage {stage_name} enter")
        _normalize_canonical_check_items(stage_data.get("exit", []), f".workflow.yaml canonical stage {stage_name} exit")
        next_stages = _require_list(stage_data.get("next", []), f".workflow.yaml canonical stage {stage_name} next")
        for target_stage in next_stages:
            if str(target_stage) not in stages:
                raise RuntimeError(f".workflow.yaml canonical stage {stage_name} next references unknown stage: {target_stage}")


def workflow_stages_from_spec(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return stages from a provided spec mapping."""
    stages = spec.get("stages", {})
    if not isinstance(stages, dict):
        raise RuntimeError(".workflow.yaml must define a stages mapping.")
    return stages


def path_policy_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalized path policy for one provided spec mapping."""
    policy = _require_mapping(spec.get("path_policy", {}), ".workflow.yaml path_policy")
    sensitive_paths = _require_list(policy.get("sensitive_paths", []), ".workflow.yaml path_policy.sensitive_paths")
    protected = _require_list(policy.get("protected_paths", spec.get("protected_paths", [])), ".workflow.yaml path_policy.protected_paths")
    return {
        "sensitive_paths": [str(item) for item in sensitive_paths],
        "protected_paths": [str(item) for item in protected],
    }


def failure_policy_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalized failure policy for one provided spec mapping."""
    policy = _require_mapping(spec.get("failure_policy", {}), ".workflow.yaml failure_policy")
    roots = _require_list(policy.get("fingerprint_roots", ["src", "tests"]), ".workflow.yaml failure_policy.fingerprint_roots")
    return {
        "repeat_threshold": int(policy.get("repeat_threshold", 2)),
        "fingerprint_roots": [str(item) for item in roots],
    }


def finalization_policy_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalized finalization policy for one provided spec mapping."""
    policy = _require_mapping(spec.get("finalization_policy", {}), ".workflow.yaml finalization_policy")
    rule_messages = _require_mapping(policy.get("rule_messages", {}), ".workflow.yaml finalization_policy.rule_messages")
    rules = _require_list(policy.get("required_rules", []), ".workflow.yaml finalization_policy.required_rules")
    return {
        "required_rules": [str(item) for item in rules],
        "rule_messages": {str(key): str(value) for key, value in rule_messages.items()},
    }


def session_start_defaults_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalized session-start defaults for one provided spec mapping."""
    config = _require_mapping(spec.get("session_start_defaults", {}), ".workflow.yaml session_start_defaults")
    skill_id = str(config.get("navigator_skill", "")).strip()
    if not skill_id:
        raise RuntimeError(".workflow.yaml session_start_defaults.navigator_skill must be a non-empty string.")
    return {"navigator_skill": skill_id}


def stage_write_policy_from_spec(spec: dict[str, Any], stage: str) -> dict[str, list[str]]:
    """Normalized stage write policy for one provided spec mapping."""
    stages = workflow_stages_from_spec(spec)
    policy = stages.get(stage, stages.get("IDLE", {})).get("write_policy", {})
    if not isinstance(policy, dict):
        raise RuntimeError(f".workflow.yaml stage {stage} write_policy must be a mapping.")
    writable = _require_list(policy.get("writable_paths", []), f".workflow.yaml stage {stage} write_policy.writable_paths")
    denied = _require_list(policy.get("denied_paths", []), f".workflow.yaml stage {stage} write_policy.denied_paths")
    return {
        "writable_paths": [str(item) for item in writable],
        "denied_paths": [str(item) for item in denied],
    }


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


def _legacy_human_allowed(stage_data: dict[str, Any]) -> bool:
    """Whether the current legacy stage allows a human stop/handoff."""
    return stage_data.get("forbid_needs_human") is None


def _legacy_entry_stage(flat_spec: dict[str, Any]) -> str:
    """Derive the canonical entry stage from legacy transitions."""
    explicit_entry = flat_spec.get("entry_stage")
    if isinstance(explicit_entry, str) and explicit_entry.strip():
        return explicit_entry
    metadata = flat_spec.get("metadata", {})
    if isinstance(metadata, dict):
        metadata_entry = metadata.get("entry")
        if isinstance(metadata_entry, str) and metadata_entry.strip():
            return metadata_entry
    idle_targets = workflow_stages_from_spec(flat_spec).get("IDLE", {}).get("allowed_next_stages", [])
    if isinstance(idle_targets, list) and idle_targets:
        return str(idle_targets[0])
    start_stages = flat_spec.get("wizard_defaults", {}).get("start_stages", [])
    if isinstance(start_stages, list) and start_stages:
        return str(start_stages[0])
    return "IDLE"


def _compat_stage_from_required_command(flat_spec: dict[str, Any], command_name: str) -> str | None:
    """Find one legacy stage by one required command entry condition."""
    for stage_name in workflow_stages_from_spec(flat_spec):
        for item in stage_entry_conditions_from_spec(flat_spec, stage_name):
            if item.get("rule") == "required_command" and item.get("value") == command_name:
                return str(stage_name)
    return None


def _compat_stage_from_expected_artifact(flat_spec: dict[str, Any], artifact_path: str) -> str | None:
    """Find one legacy stage by one expected artifact path."""
    for stage_name, stage_data in workflow_stages_from_spec(flat_spec).items():
        expected = stage_data.get("artifacts_expected", [])
        if isinstance(expected, list) and artifact_path in expected:
            return str(stage_name)
        for item in stage_required_artifact_rules_from_spec(flat_spec, stage_name):
            if item["path"] == artifact_path:
                return str(stage_name)
    return None


def _compat_stage_from_required_artifact(flat_spec: dict[str, Any], artifact_path: str) -> str | None:
    """Find one legacy stage by one required artifact path."""
    for stage_name in workflow_stages_from_spec(flat_spec):
        for item in stage_required_artifact_rules_from_spec(flat_spec, stage_name):
            if item["path"] == artifact_path:
                return str(stage_name)
    return None


def normalize_legacy_to_canonical(flat_spec: dict[str, Any]) -> dict[str, Any]:
    """Project the current legacy workflow model into the new canonical shape."""
    metadata = _require_mapping(flat_spec.get("metadata", {}), ".workflow.yaml metadata")
    stages = workflow_stages_from_spec(flat_spec)
    completion_stage = _compat_stage_from_required_command(flat_spec, "mark-done") or "DONE"

    canonical_stages: dict[str, Any] = {}
    for stage_name, stage_data in stages.items():
        required_items: list[str | dict[str, str]] = []
        for entry in stage_required_artifact_rules_from_spec(flat_spec, stage_name):
            if set(entry.keys()) == {"path"}:
                required_items.append(entry["path"])
            else:
                required_items.append(dict(entry))

        canonical_stages[stage_name] = {
            "goal": str(stage_data.get("goal", "")),
            "plan": _legacy_plan_mode(stage_name),
            "allow": {
                "write": stage_write_policy_from_spec(flat_spec, stage_name)["writable_paths"],
                "actions": [str(item) for item in stage_data.get("allowed_actions", [])],
                "stop": _legacy_stop_allowed(stage_name),
                "human": _legacy_human_allowed(stage_data),
            },
            "deny": {
                "write": stage_write_policy_from_spec(flat_spec, stage_name)["denied_paths"],
                "actions": [str(item) for item in stage_data.get("forbidden_actions", [])],
            },
            "enter": [dict(item) for item in stage_entry_conditions_from_spec(flat_spec, stage_name)],
            "exit": required_items,
            "next": [str(item) for item in stage_data.get("allowed_next_stages", [])],
            "final": stage_name == completion_stage,
        }

    return {
        "version": 2,
        "workflow": {
            "id": str(metadata.get("id", "")),
            "title": str(metadata.get("title", "")),
            "description": str(metadata.get("description", "")),
            "entry": _legacy_entry_stage(flat_spec),
        },
        "globals": {
            "protected": path_policy_from_spec(flat_spec)["protected_paths"],
            "sensitive": path_policy_from_spec(flat_spec)["sensitive_paths"],
            "failures": failure_policy_from_spec(flat_spec),
            "finalize": {
                "require": [{"rule": rule_name} for rule_name in finalization_policy_from_spec(flat_spec)["required_rules"]],
                "messages": finalization_policy_from_spec(flat_spec)["rule_messages"],
            },
            "session_start": {
                "navigator_skill": session_start_defaults_from_spec(flat_spec)["navigator_skill"],
            },
            "compat": {
                "completion_ready_stage": _compat_stage_from_required_command(flat_spec, "ready-to-summarize"),
                "completion_stage": completion_stage,
                "verification_stage": _compat_stage_from_expected_artifact(flat_spec, ".agent/artifacts/final-verification.log"),
                "expected_failure_stage": _compat_stage_from_expected_artifact(flat_spec, ".agent/artifacts/red-test.log"),
                "failure_analysis_stage": _compat_stage_from_required_artifact(flat_spec, ".agent/artifacts/failure-analysis.md"),
                "human_handoff_stage": "NEEDS_HUMAN" if "NEEDS_HUMAN" in stages else None,
            },
        },
        "stages": canonical_stages,
    }


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


def stage_required_artifact_rules_from_spec(spec: dict[str, Any], stage: str) -> list[dict[str, str]]:
    """Normalized required artifact rules for one provided spec mapping."""
    artifacts = workflow_stages_from_spec(spec).get(stage, workflow_stages_from_spec(spec).get("IDLE", {})).get("artifacts_required", [])
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


def stage_entry_conditions_from_spec(spec: dict[str, Any], stage: str, from_stage: str | None = None) -> list[dict[str, str]]:
    """Stage entry conditions for one provided spec mapping."""
    rules = workflow_stages_from_spec(spec).get(stage, workflow_stages_from_spec(spec).get("IDLE", {}))
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


@lru_cache(maxsize=1)
def canonical_workflow_spec() -> dict[str, Any]:
    """Projected canonical workflow model used by the runtime compatibility layer."""
    canonical = normalize_legacy_to_canonical(load_workflow_spec())
    validate_canonical_workflow_spec(canonical)
    return canonical


def canonical_entry_stage() -> str:
    """Canonical entry stage."""
    workflow = _require_mapping(canonical_workflow_spec().get("workflow", {}), ".workflow.yaml canonical workflow")
    return str(workflow.get("entry", "IDLE"))


def canonical_stage_spec(stage: str) -> dict[str, Any]:
    """Canonical stage spec."""
    stages = _require_mapping(canonical_workflow_spec().get("stages", {}), ".workflow.yaml canonical stages")
    fallback = stages.get("IDLE", {})
    return _require_mapping(stages.get(stage, fallback), f".workflow.yaml canonical stage {stage}")


def canonical_stage_next(stage: str) -> list[str]:
    """Canonical next stages for one stage."""
    return [str(item) for item in _require_list(canonical_stage_spec(stage).get("next", []), f".workflow.yaml canonical stage {stage} next")]


def canonical_stage_stop_allowed(stage: str) -> bool:
    """Whether the stage allows ending the current interaction."""
    allow = _require_mapping(canonical_stage_spec(stage).get("allow", {}), f".workflow.yaml canonical stage {stage} allow")
    return bool(allow.get("stop", False))


def canonical_stage_human_allowed(stage: str) -> bool:
    """Whether the stage allows human intervention."""
    allow = _require_mapping(canonical_stage_spec(stage).get("allow", {}), f".workflow.yaml canonical stage {stage} allow")
    return bool(allow.get("human", False))


def canonical_stage_plan_mode(stage: str) -> str:
    """Canonical stage plan mode."""
    return str(canonical_stage_spec(stage).get("plan", "deny"))


def canonical_final_stages() -> list[str]:
    """Canonical final stages."""
    return [
        stage_name
        for stage_name, stage_data in _require_mapping(canonical_workflow_spec().get("stages", {}), ".workflow.yaml canonical stages").items()
        if bool(_require_mapping(stage_data, f".workflow.yaml canonical stage {stage_name}").get("final", False))
    ]


def _canonical_compat_stage(name: str) -> str | None:
    compat = _require_mapping(canonical_workflow_spec().get("globals", {}).get("compat", {}), ".workflow.yaml canonical globals.compat")
    stage_name = compat.get(name)
    return stage_name if isinstance(stage_name, str) and stage_name.strip() else None


def canonical_completion_stage() -> str:
    """Canonical completion stage."""
    compat_stage = _canonical_compat_stage("completion_stage")
    if compat_stage:
        return compat_stage
    final_stages = canonical_final_stages()
    return final_stages[0] if final_stages else "DONE"


def canonical_completion_ready_stage() -> str:
    """Canonical completion-ready stage used by the legacy command."""
    return _canonical_compat_stage("completion_ready_stage") or canonical_completion_stage()


def canonical_failure_analysis_stage() -> str | None:
    """Canonical failure-analysis stage used by the compatibility adapter."""
    return _canonical_compat_stage("failure_analysis_stage")


def canonical_expected_failure_stage() -> str | None:
    """Canonical expected-failure stage used by the compatibility adapter."""
    return _canonical_compat_stage("expected_failure_stage")


def canonical_verification_stage() -> str | None:
    """Canonical verification stage used by the compatibility adapter."""
    return _canonical_compat_stage("verification_stage")


def protected_paths() -> list[str]:
    """Protected paths."""
    return path_policy()["protected_paths"]


def path_policy() -> dict[str, Any]:
    """Normalized path policy."""
    return path_policy_from_spec(load_workflow_spec())


def failure_policy() -> dict[str, Any]:
    """Normalized failure policy."""
    return failure_policy_from_spec(load_workflow_spec())


def finalization_policy() -> dict[str, Any]:
    """Normalized finalization policy."""
    return finalization_policy_from_spec(load_workflow_spec())


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
    return session_start_defaults_from_spec(load_workflow_spec())


def stage_write_policy(stage: str) -> dict[str, list[str]]:
    """Normalized stage write policy."""
    return stage_write_policy_from_spec(load_workflow_spec(), stage)


def complete_step_allowed_from_stages() -> list[str]:
    """Complete step allowed from stages."""
    return [
        stage_name
        for stage_name, stage_data in workflow_stages().items()
        if stage_data.get("allows_complete_step") is True or stage_data.get("plan_mode") == "advance"
    ]
