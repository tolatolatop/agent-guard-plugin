"""Claude Code installation and removal integration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import (
    RuntimeIntegration,
    build_plan_result,
    dedupe_hook_entries,
    hook_change,
    read_json_if_exists,
    remove_marked_hook_entries,
    skill_change,
    uv_bridge_command,
    write_json,
)
from .skills import install_native_skills_bundle, remove_legacy_skill_copies

PLUGIN_NAME = "r2c"
PLUGIN_DISPLAY_NAME = "R2C Agent Guard"
SKILLS_DIR_MARKETPLACE = "skills-dir"
SKILLS_DIR_PLUGIN_ID = f"{PLUGIN_NAME}@{SKILLS_DIR_MARKETPLACE}"
PLUGIN_RELATIVE_DIR = f".claude/skills/{PLUGIN_NAME}"
PLUGIN_SKILLS_RELATIVE_DIR = f"{PLUGIN_RELATIVE_DIR}/skills"
HOOK_MARKER = "agent-guard-bridge"


def skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return Claude's skills directory inside the local directory plugin."""
    return plugin_install_dir(scope, cwd, home_dir) / "skills"


def plugin_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return Claude's local skills-directory plugin root."""
    skills_root = cwd / ".claude" / "skills" if scope == "project" else home_dir / ".claude" / "skills"
    return skills_root / PLUGIN_NAME


def config_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return the Claude settings file for an installation scope."""
    return cwd / ".claude" / "settings.local.json" if scope == "project" else home_dir / ".claude" / "settings.json"


def global_config_file(home_dir: Path) -> Path:
    """Return Claude's global project-state file."""
    return home_dir / ".claude.json"


def install_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    *,
    root_dir: Path | None = None,
    workflow_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Install Claude workflow skills in its native directory layout."""
    return install_native_skills_bundle(
        target_dir,
        plugin_root,
        include_matches,
        exclude_matches,
        empty_error="No Claude workflow skills were installed.",
        root_dir=root_dir,
        workflow_id=workflow_id,
    )


def install_plugin_manifest(plugin_dir: Path) -> str:
    """Write the Claude directory-plugin manifest."""
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    write_json(
        manifest_path,
        {
            "name": PLUGIN_NAME,
            "displayName": PLUGIN_DISPLAY_NAME,
            "version": "1.0.0",
            "description": "Workflow guard skills for agent-guard.",
        },
    )
    return str(manifest_path)


def enable_skills_dir_plugin(config: dict[str, Any]) -> dict[str, Any]:
    """Enable the local Claude skills-directory plugin."""
    next_config = dict(config)
    enabled_plugins = next_config.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict):
        enabled_plugins = {}
    else:
        enabled_plugins = dict(enabled_plugins)
    enabled_plugins[SKILLS_DIR_PLUGIN_ID] = True
    next_config["enabledPlugins"] = enabled_plugins
    return next_config


def disable_skills_dir_plugin(config: dict[str, Any]) -> dict[str, Any]:
    """Remove agent-guard's Claude directory-plugin enablement."""
    next_config = dict(config)
    enabled_plugins = next_config.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict):
        return next_config
    cleaned_plugins = dict(enabled_plugins)
    cleaned_plugins.pop(SKILLS_DIR_PLUGIN_ID, None)
    if cleaned_plugins:
        next_config["enabledPlugins"] = cleaned_plugins
    else:
        next_config.pop("enabledPlugins", None)
    return next_config


def remove_legacy_standalone_skills(skills_root: Path, plugin_root: Path, source_root: Path) -> None:
    """Remove skill copies predating the Claude directory plugin."""
    remove_legacy_skill_copies(skills_root, plugin_root, source_root)


def build_hooks(plugin_root: Path, skills_dir: Path) -> dict[str, Any]:
    """Build Claude lifecycle hooks."""
    return {
        "SessionStart": [
            {
                "matcher": "startup|clear|compact",
                "hooks": [
                    {
                        "type": "command",
                        "command": uv_bridge_command(plugin_root, "session-start", skills_dir),
                        "async": False,
                    }
                ],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "pre-write", skills_dir)}],
            },
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "pre-command", skills_dir)}],
            },
        ],
        "PostToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "post-command", skills_dir)}],
            }
        ],
        "Stop": [
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "stop", skills_dir)}],
            }
        ],
    }


def merge_hooks(existing_hooks: dict[str, Any], new_hooks: dict[str, Any], marker: str) -> dict[str, Any]:
    """Merge agent-guard hooks while preserving unrelated Claude hooks."""
    merged = dict(existing_hooks)
    for event_name, entries in new_hooks.items():
        existing_entries = merged.get(event_name, [])
        if not isinstance(existing_entries, list):
            existing_entries = []
        merged[event_name] = [*dedupe_hook_entries(existing_entries, marker), *entries]
    return merged


def activate_project_plugin(cwd: Path, home_dir: Path) -> str:
    """Trust a project so Claude can load its directory plugin immediately."""
    config_path = global_config_file(home_dir)
    config = read_json_if_exists(config_path, {})
    projects = config.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    else:
        projects = dict(projects)

    project_key = str(cwd)
    project_config = projects.get(project_key)
    if not isinstance(project_config, dict):
        project_config = {}
    else:
        project_config = dict(project_config)
    project_config["hasTrustDialogAccepted"] = True
    seen_count = project_config.get("projectOnboardingSeenCount")
    project_config["projectOnboardingSeenCount"] = max(seen_count if isinstance(seen_count, int) else 0, 1)
    projects[project_key] = project_config
    config["projects"] = projects
    write_json(config_path, config)
    return str(config_path)


def install(
    cwd: Path,
    home_dir: Path,
    scope: str,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Install the Claude Code integration."""
    config_path = config_file(scope, cwd, home_dir)
    config = read_json_if_exists(config_path, {})
    claude_plugin_dir = plugin_install_dir(scope, cwd, home_dir)
    skills_dir = skills_install_dir(scope, cwd, home_dir)
    remove_legacy_standalone_skills(claude_plugin_dir.parent, claude_plugin_dir, plugin_root)
    skill_files, selection_warnings = install_skills_bundle(
        skills_dir,
        plugin_root,
        include_matches,
        exclude_matches,
        root_dir=cwd,
        workflow_id=workflow_id,
    )
    manifest_file = install_plugin_manifest(claude_plugin_dir)
    config["hooks"] = merge_hooks(config.get("hooks", {}), build_hooks(plugin_root, skills_dir), HOOK_MARKER)
    config = enable_skills_dir_plugin(config)
    write_json(config_path, config)
    activated_file = activate_project_plugin(cwd, home_dir) if scope == "project" else None
    return {
        "runtime": "claude-code",
        "scope": scope,
        "files_written": [str(config_path), *([activated_file] if activated_file else []), manifest_file, *skill_files],
        "notes": [
            *selection_warnings,
            "Installed Claude Code hooks into a settings JSON file.",
            "Claude Code passes hook payloads over stdin and can block PreToolUse or Stop hooks with exit code 2.",
            "Session-start and status flows will auto-start agent-guard-fuse when the runtime binary is installed, "
            "so .agent/state.json and .agent/plan.yaml stay mounted under managed protection.",
            f"Enabled the local Claude skills-directory plugin as {SKILLS_DIR_PLUGIN_ID}.",
            *(
                ["Marked the project trusted in Claude's global state so project-scope directory plugins load immediately."]
                if activated_file
                else []
            ),
            f"Workflow skills were installed into Claude's {PLUGIN_NAME} skills-directory plugin at "
            f"{PLUGIN_SKILLS_RELATIVE_DIR}/<skill>/SKILL.md and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def _clean_config(config: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    cleaned_hooks, removed = remove_marked_hook_entries(hooks, HOOK_MARKER)
    next_config = disable_skills_dir_plugin(config)
    plugin_enablement_removed = next_config != config
    if cleaned_hooks:
        next_config["hooks"] = cleaned_hooks
    else:
        next_config.pop("hooks", None)
    return next_config, removed, plugin_enablement_removed


def plan_uninstall(
    cwd: Path,
    home_dir: Path,
    scope: str,
    *,
    include_skills: bool = True,
) -> dict[str, Any]:
    """Plan removal of Claude hooks and optionally its installed skills."""
    config_path = config_file(scope, cwd, home_dir)
    changes: list[dict[str, str]] = []
    notes: list[str] = []
    if config_path.exists():
        config = read_json_if_exists(config_path, {})
        next_config, removed, plugin_enablement_removed = _clean_config(config)
        if removed or plugin_enablement_removed:
            if next_config:
                changes.append(
                    hook_change("update", config_path, "Remove agent-guard hook entries from Claude Code settings.")
                )
                notes.append(json.dumps(next_config, indent=2))
            else:
                changes.append(
                    hook_change(
                        "delete",
                        config_path,
                        "Delete the Claude Code settings file because it only contained agent-guard hooks.",
                    )
                )

    plugin_dir = plugin_install_dir(scope, cwd, home_dir)
    if include_skills and plugin_dir.exists():
        changes.append(skill_change(plugin_dir))
    return build_plan_result("claude-code", scope, changes, notes)


def apply_config_update(cwd: Path, home_dir: Path, scope: str) -> None:
    """Apply the Claude settings update described by an uninstall plan."""
    target_path = config_file(scope, cwd, home_dir)
    config = read_json_if_exists(target_path, {})
    next_config, _, _ = _clean_config(config)
    if next_config:
        write_json(target_path, next_config)
    elif target_path.exists():
        target_path.unlink()


INTEGRATION = RuntimeIntegration(
    name="claude-code",
    install=install,
    plan_uninstall=plan_uninstall,
    apply_config_update=apply_config_update,
)
