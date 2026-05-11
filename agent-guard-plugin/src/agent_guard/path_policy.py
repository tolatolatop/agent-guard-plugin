from __future__ import annotations

import re
from typing import Any

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

PROTECTED_STATE_PATHS = [
    ".agent/state.json",
]

STAGE_MANAGED_PATHS = {
    "IDLE": (".agent/**",),
    "CLARIFYING": (".agent/**",),
    "DESIGNING": (".agent/**",),
    "PLANNING": (".agent/**",),
    "REVIEW": (".agent/**",),
    "VERIFY": (".agent/artifacts/**",),
    "READY_TO_SUMMARIZE": (),
    "NEEDS_FAILURE_ANALYSIS": (".agent/artifacts/**",),
    "NEEDS_HUMAN": (".agent/**",),
    "DONE": (".agent/**",),
}


def normalize_path(target_path: str) -> str:
    return target_path.replace("\\", "/").removeprefix("./")


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
    return stage in STAGE_MANAGED_PATHS


def is_allowed_managed_path(stage: str, target_path: str) -> bool:
    allowed_paths = STAGE_MANAGED_PATHS.get(stage, ())
    return bool(allowed_paths) and matches_any(target_path, allowed_paths)


def decide_write(state: dict[str, Any], target_path: str) -> dict[str, str]:
    normalized = normalize_path(target_path)
    stage = state["stage"]

    if matches_any(normalized, PROTECTED_STATE_PATHS):
        return blocked(
            "Path .agent/state.json is managed by agent-guard and cannot be edited directly. "
            "Use agent-guard commands to change task state."
        )

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

    if stage == "READY_TO_SUMMARIZE":
        return blocked("Current stage is READY_TO_SUMMARIZE. Further code changes are not allowed.")

    if stage == "RED_TEST" and normalized.startswith("src/"):
        return blocked("Current stage is RED_TEST. src/** is forbidden. Write tests/** first.")

    if matches_any(normalized, state.get("forbidden_paths", [])):
        return blocked(f"Path {normalized} matches forbidden path policy for stage {stage}.")

    if is_sensitive_path(normalized):
        return blocked(f"Path {normalized} is sensitive and requires human approval or an explicit plan allowance.")

    allowed_paths = state.get("allowed_paths", [])
    if allowed_paths and not matches_any(normalized, allowed_paths):
        return blocked(f"Path {normalized} is outside allowed paths for stage {stage}.")

    return allowed(f"Path {normalized} is allowed during {stage}.")
