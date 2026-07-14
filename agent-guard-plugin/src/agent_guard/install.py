"""CLI-facing orchestration for supported runtime integrations.

Runtime-specific paths, generated configuration, installation, and uninstall
planning live in :mod:`agent_guard.runtime_integrations`. This module keeps the
existing public helpers and command behavior as a compatibility facade.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, TextIO

from .interactive import confirm_action, prompt_choice, prompt_text
from .runtime_integrations import SUPPORTED_RUNTIMES, get_runtime_integration
from .runtime_integrations import claude_code as _claude
from .runtime_integrations import codex as _codex
from .runtime_integrations import opencode as _opencode
from .runtime_integrations.common import (
    build_plan_result,
    cleanup_empty_dirs,
    dedupe_hook_entries,
    read_json_if_exists,
    remove_marked_hook_entries,
    shell_assignment,
    shell_command,
    uv_bridge_command,
    write_json,
)
from .runtime_integrations.skills import (
    install_flat_skills_bundle,
    install_native_skills_bundle,
    install_selection_warning,
    packaged_skills_dir,
    resolve_skill_filters,
    selected_skill_sources,
    selected_skill_sources_with_fallback,
    shared_skills_install_dir,
    skill_slug_from_source,
    source_skills_dir,
    workflow_install_defaults,
)

SUPPORTED_SCOPES = ("project", "user")
SHORT_FLAG_ALIASES = {"-i": "interactive", "-r": "runtime", "-s": "scope"}
MULTI_VALUE_FLAGS = {"match", "exclude-match"}

# Compatibility exports for callers that used the former monolithic module.
_CLAUDE_PLUGIN_NAME = _claude.PLUGIN_NAME
_CLAUDE_PLUGIN_DISPLAY_NAME = _claude.PLUGIN_DISPLAY_NAME
_CLAUDE_SKILLS_DIR_MARKETPLACE = _claude.SKILLS_DIR_MARKETPLACE
_CLAUDE_SKILLS_DIR_PLUGIN_ID = _claude.SKILLS_DIR_PLUGIN_ID
_CLAUDE_PLUGIN_RELATIVE_DIR = _claude.PLUGIN_RELATIVE_DIR
_CLAUDE_PLUGIN_SKILLS_RELATIVE_DIR = _claude.PLUGIN_SKILLS_RELATIVE_DIR

claude_skills_install_dir = _claude.skills_install_dir
claude_plugin_install_dir = _claude.plugin_install_dir
claude_config_file = _claude.config_file
claude_global_config_file = _claude.global_config_file
install_claude_skills_bundle = _claude.install_skills_bundle
install_claude_plugin_manifest = _claude.install_plugin_manifest
enable_claude_skills_dir_plugin = _claude.enable_skills_dir_plugin
disable_claude_skills_dir_plugin = _claude.disable_skills_dir_plugin
remove_legacy_claude_standalone_skills = _claude.remove_legacy_standalone_skills
build_claude_hooks = _claude.build_hooks
merge_claude_hooks = _claude.merge_hooks
activate_claude_project_plugin = _claude.activate_project_plugin
install_claude_code = _claude.install
plan_uninstall_claude_code = _claude.plan_uninstall

codex_skills_install_dir = _codex.skills_install_dir
codex_hooks_file = _codex.hooks_file
build_codex_hooks = _codex.build_hooks
install_codex = _codex.install
plan_uninstall_codex = _codex.plan_uninstall

opencode_skills_install_dir = _opencode.skills_install_dir
opencode_plugin_file = _opencode.plugin_file
build_opencode_plugin_source = _opencode.build_plugin_source
install_opencode = _opencode.install
plan_uninstall_opencode = _opencode.plan_uninstall

_remove_marked_hook_entries = remove_marked_hook_entries
_cleanup_empty_dirs = cleanup_empty_dirs
_build_plan_result = build_plan_result


def install_opencode_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    *,
    root_dir: Path | None = None,
    workflow_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Compatibility wrapper for installing OpenCode skills."""
    return install_native_skills_bundle(
        target_dir,
        plugin_root,
        include_matches,
        exclude_matches,
        empty_error="No OpenCode workflow skills were installed.",
        root_dir=root_dir,
        workflow_id=workflow_id,
    )


def _csv_patterns(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def prompt_install_options(
    flags: dict[str, Any], input_stream: TextIO, output: TextIO
) -> dict[str, Any]:
    """Prompt for all install options in interactive mode."""
    updated = dict(flags)
    default_runtime = str(updated.get("runtime") or "codex")
    default_scope = str(updated.get("scope") or "project")
    updated["runtime"] = prompt_choice("Runtime", list(SUPPORTED_RUNTIMES), input_stream, output, default_runtime)
    updated["scope"] = prompt_choice("Scope", list(SUPPORTED_SCOPES), input_stream, output, default_scope)

    match_default = (
        ",".join(str(item) for item in updated.get("match", []))
        if isinstance(updated.get("match"), list)
        else ""
    )
    exclude_default = (
        ",".join(str(item) for item in updated.get("exclude-match", []))
        if isinstance(updated.get("exclude-match"), list)
        else ""
    )
    include_raw = prompt_text(
        "Include skill regexes (comma-separated, blank for defaults)", input_stream, output, default=match_default
    )
    exclude_raw = prompt_text(
        "Exclude skill regexes (comma-separated, blank for defaults)", input_stream, output, default=exclude_default
    )
    include_patterns = _csv_patterns(include_raw)
    exclude_patterns = _csv_patterns(exclude_raw)
    if include_patterns:
        updated["match"] = include_patterns
    else:
        updated.pop("match", None)
    if exclude_patterns:
        updated["exclude-match"] = exclude_patterns
    else:
        updated.pop("exclude-match", None)
    updated["wizard"] = bool(updated.get("wizard")) or confirm_action(
        "Run setup wizard after install?", input_stream, output
    )
    return updated


def prompt_missing_install_axes(
    flags: dict[str, Any], input_stream: TextIO, output: TextIO
) -> dict[str, Any]:
    """Prompt only for a missing runtime or scope."""
    updated = dict(flags)
    prompted = False
    if updated.get("runtime") not in SUPPORTED_RUNTIMES:
        updated["runtime"] = prompt_choice(
            "Runtime", list(SUPPORTED_RUNTIMES), input_stream, output, default="codex"
        )
        prompted = True
    if updated.get("scope") not in SUPPORTED_SCOPES:
        updated["scope"] = prompt_choice(
            "Scope", list(SUPPORTED_SCOPES), input_stream, output, default="project"
        )
        prompted = True
    if prompted and "wizard" not in updated:
        updated["wizard"] = confirm_action("Run setup wizard after install?", input_stream, output)
    return updated


def parse_flags(args: list[str]) -> dict[str, Any]:
    """Parse the install/uninstall command's compact flag format."""
    flags: dict[str, Any] = {}
    index = 0
    while index < len(args):
        current = args[index]
        if current in SHORT_FLAG_ALIASES:
            key = SHORT_FLAG_ALIASES[current]
            next_value = args[index + 1] if index + 1 < len(args) else None
            if next_value is None or next_value.startswith("-"):
                flags[key] = True
                index += 1
                continue
            if key in MULTI_VALUE_FLAGS:
                flags.setdefault(key, []).append(next_value)
            else:
                flags[key] = next_value
            index += 2
            continue
        if not current.startswith("--"):
            index += 1
            continue
        key = current[2:]
        next_value = args[index + 1] if index + 1 < len(args) else None
        if next_value is None or next_value.startswith("--"):
            flags[key] = True
            index += 1
            continue
        if key in MULTI_VALUE_FLAGS:
            flags.setdefault(key, []).append(next_value)
        else:
            flags[key] = next_value
        index += 2
    return flags


def _validate_runtime_and_scope(flags: dict[str, Any]) -> tuple[str, str]:
    runtime = flags.get("runtime")
    scope = flags.get("scope", "project")
    if runtime not in SUPPORTED_RUNTIMES:
        raise RuntimeError(f"Missing or unsupported --runtime. Expected one of: {', '.join(SUPPORTED_RUNTIMES)}")
    if scope not in SUPPORTED_SCOPES:
        raise RuntimeError(f"Unsupported --scope. Expected one of: {', '.join(SUPPORTED_SCOPES)}")
    return str(runtime), str(scope)


def install_runtime(
    argv: list[str],
    cwd: Path,
    home_dir: Path | None,
    plugin_root: Path,
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
) -> dict[str, Any]:
    """Install one registered runtime integration."""
    flags = parse_flags(argv)
    install_input = input_stream or sys.stdin
    install_output = output or sys.stdout
    flags = (
        prompt_install_options(flags, install_input, install_output)
        if bool(flags.get("interactive"))
        else prompt_missing_install_axes(flags, install_input, install_output)
    )
    runtime, scope = _validate_runtime_and_scope(flags)
    resolved_home = home_dir or Path(os.path.expanduser("~"))
    include_matches = [str(item) for item in flags.get("match", [])] if isinstance(flags.get("match"), list) else []
    exclude_matches = [str(item) for item in flags.get("exclude-match", [])] if isinstance(flags.get("exclude-match"), list) else []
    workflow_id = str(flags["workflow"]) if "workflow" in flags else None
    result = get_runtime_integration(runtime).install(
        cwd, resolved_home, scope, plugin_root, include_matches, exclude_matches, workflow_id
    )
    if bool(flags.get("wizard")):
        from .wizard import run_wizard

        result["wizard"] = run_wizard(cwd, install_input, install_output)
    else:
        result["wizard"] = None
    return result


def plan_uninstall_runtime(argv: list[str], cwd: Path, home_dir: Path | None) -> dict[str, Any]:
    """Plan complete removal of one registered runtime integration."""
    runtime, scope = _validate_runtime_and_scope(parse_flags(argv))
    resolved_home = home_dir or Path(os.path.expanduser("~"))
    return get_runtime_integration(runtime).plan_uninstall(
        cwd, resolved_home, scope, include_skills=True
    )


def _render_uninstall_preview(plan: dict[str, Any], output: TextIO) -> None:
    output.write("The following changes will be applied:\n")
    for change in plan["changes"]:
        output.write(f"- {change['action']}: {change['path']}\n")
        output.write(f"  {change['details']}\n")


def _confirm_uninstall(output: TextIO, input_stream: TextIO) -> bool:
    return confirm_action("Proceed with uninstall?", input_stream, output)


def apply_uninstall_plan(plan: dict[str, Any], cwd: Path, home_dir: Path | None) -> dict[str, Any]:
    """Apply a plan produced by a registered runtime integration."""
    scope = str(plan["scope"])
    resolved_home = home_dir or Path(os.path.expanduser("~"))
    integration = get_runtime_integration(str(plan["runtime"]))
    for change in plan["changes"]:
        file_path = Path(change["path"])
        if change["action"] == "delete":
            if file_path.exists():
                file_path.unlink()
                if file_path.parent.name in {".claude", ".codex"}:
                    cleanup_empty_dirs(file_path.parent, resolved_home if scope == "user" else cwd)
                elif file_path.parent.name == "plugins":
                    stop_dir = resolved_home / ".config" if scope == "user" else cwd
                    cleanup_empty_dirs(file_path.parent, stop_dir)
        elif change["action"] == "delete-tree":
            if file_path.exists():
                shutil.rmtree(file_path)
        elif change["action"] == "update":
            integration.apply_config_update(cwd, resolved_home, scope)
    return {
        "runtime": plan["runtime"],
        "scope": plan["scope"],
        "changes_applied": plan["changes"],
        "cancelled": False,
    }


def uninstall_runtime(
    argv: list[str],
    cwd: Path,
    home_dir: Path | None,
    output: TextIO,
    input_stream: TextIO,
) -> dict[str, Any]:
    """Preview, confirm, and apply a runtime uninstall."""
    flags = parse_flags(argv)
    plan = plan_uninstall_runtime(argv, cwd, home_dir)
    if not plan["changes"]:
        return {
            "runtime": plan["runtime"],
            "scope": plan["scope"],
            "changes_applied": [],
            "cancelled": False,
            "message": "No agent-guard installation was found for the requested runtime and scope.",
        }
    _render_uninstall_preview(plan, output)
    if not bool(flags.get("yes")) and not _confirm_uninstall(output, input_stream):
        return {
            "runtime": plan["runtime"],
            "scope": plan["scope"],
            "changes_applied": [],
            "cancelled": True,
            "message": "Uninstall cancelled.",
        }
    return apply_uninstall_plan(plan, cwd, home_dir)


def stop_all_hooks(cwd: Path, home_dir: Path | None) -> dict[str, Any]:
    """Disable hook configurations for all runtimes while preserving skills."""
    resolved_home = home_dir or Path(os.path.expanduser("~"))
    results: list[dict[str, Any]] = []
    for runtime in SUPPORTED_RUNTIMES:
        integration = get_runtime_integration(runtime)
        for scope in SUPPORTED_SCOPES:
            plan = integration.plan_uninstall(cwd, resolved_home, scope, include_skills=False)
            if plan["changes"]:
                results.append(apply_uninstall_plan(plan, cwd, resolved_home))
    return {"ok": True, "results": results}
