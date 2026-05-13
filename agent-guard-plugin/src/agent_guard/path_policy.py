from __future__ import annotations

import re
from typing import Any

from .workflow_spec import protected_paths, stage_spec

SENSITIVE_PATTERNS = [
    ".github/**",
    "infra/**",
    "migrations/**",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
]

def normalize_path(target_path: str) -> str:
    normalized = target_path.replace("\\", "/").removeprefix("./")

    if normalized == ".agent" or normalized.startswith(".agent/"):
        return normalized

    agent_marker = "/.agent/"
    if agent_marker in normalized:
        return ".agent/" + normalized.rsplit(agent_marker, 1)[1].lstrip("/")
    if normalized.endswith("/.agent"):
        return ".agent"

    return normalized


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    normalized = normalize_path(pattern)
    double_placeholder = "__DOUBLE_WILDCARD__"
    single_placeholder = "__SINGLE_WILDCARD__"
    escaped = (
        normalized.replace("**", double_placeholder)
        .replace("*", single_placeholder)
    )
    escaped = re.escape(escaped)
    regex_source = escaped.replace(double_placeholder, ".*").replace(single_placeholder, "[^/]*")
    return re.compile(f"^{regex_source}$")


def matches_any(target_path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = normalize_path(target_path)
    return any(glob_to_regex(pattern).match(normalized) for pattern in patterns)


def is_sensitive_path(target_path: str) -> bool:
    return matches_any(target_path, SENSITIVE_PATTERNS)


def blocked(reason: str) -> dict[str, str]:
    return {"decision": "block", "reason": reason}


def allowed(reason: str) -> dict[str, str]:
    return {"decision": "allow", "reason": reason}


def is_stage_managed_only(stage: str) -> bool:
    return stage_spec(stage).get("writable") == "managed-only"


def is_stage_read_only(stage: str) -> bool:
    return stage_spec(stage).get("writable") == "none"


def is_allowed_managed_path(stage: str, target_path: str) -> bool:
    allowed_paths = tuple(stage_spec(stage).get("allowed_paths", []))
    return bool(allowed_paths) and matches_any(target_path, allowed_paths)


def decide_write(state: dict[str, Any], target_path: str) -> dict[str, str]:
    normalized = normalize_path(target_path)
    stage = state["stage"]
    stage_rule = stage_spec(stage)

    if matches_any(normalized, protected_paths()):
        return blocked(
            "Path .agent/state.json is managed by agent-guard and cannot be edited directly. "
            "Use agent-guard commands to change task state."
        )

    if is_stage_read_only(stage):
        return blocked(f"Current stage is {stage}. Further file edits are not allowed.")

    if is_stage_managed_only(stage) and not is_allowed_managed_path(stage, normalized):
        if state.get("task_id") is None:
            return blocked(
                f"No active task is set and stage is {stage}. "
                "Run agent-guard start-task before writing project files."
            )
        return blocked(
            f"Current stage is {stage}. Direct project file edits are not allowed in this stage. "
            "Use agent-guard workflow commands and .agent artifacts first."
        )

    stage_forbidden_paths = list(stage_rule.get("forbidden_paths", []))
    if matches_any(normalized, stage_forbidden_paths):
        return blocked(f"Path {normalized} matches forbidden path policy for stage {stage}.")

    if matches_any(normalized, state.get("forbidden_paths", [])):
        return blocked(f"Path {normalized} matches forbidden path policy for stage {stage}.")

    if is_sensitive_path(normalized):
        return blocked(f"Path {normalized} is sensitive and requires human approval or an explicit plan allowance.")

    allowed_paths = state.get("allowed_paths", [])
    if allowed_paths and not matches_any(normalized, allowed_paths):
        return blocked(f"Path {normalized} is outside allowed paths for stage {stage}.")

    return allowed(f"Path {normalized} is allowed during {stage}.")
