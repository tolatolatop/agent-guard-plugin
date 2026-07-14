"""Codex installation and removal integration."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .common import (
    RuntimeIntegration,
    build_plan_result,
    hook_change,
    read_json_if_exists,
    remove_marked_hook_entries,
    skill_change,
    uv_bridge_command,
    write_json,
)
from .skills import install_native_skills_bundle, shared_skills_install_dir

HOOK_MARKER = "agent-guard-bridge"


def skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return Codex's native skills directory."""
    return cwd / ".codex" / "skills" if scope == "project" else home_dir / ".codex" / "skills"


def hooks_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return Codex's hook configuration path."""
    return cwd / ".codex" / "hooks.json" if scope == "project" else home_dir / ".codex" / "hooks.json"


def build_hooks(plugin_root: Path, skills_dir: Path) -> dict[str, Any]:
    """Build Codex's Claude-compatible lifecycle hook document."""
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "session-start", skills_dir)}],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit|Bash",
                    "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "pre-dispatch", skills_dir)}],
                }
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
    }


def install(
    cwd: Path,
    home_dir: Path,
    scope: str,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Install the Codex integration."""
    hooks_path = hooks_file(scope, cwd, home_dir)
    skills_dir = skills_install_dir(scope, cwd, home_dir)
    skill_files, selection_warnings = install_native_skills_bundle(
        skills_dir,
        plugin_root,
        include_matches,
        exclude_matches,
        empty_error="No Codex workflow skills were installed.",
        root_dir=cwd,
        workflow_id=workflow_id,
    )
    legacy_skills_dir = shared_skills_install_dir(scope, cwd, home_dir)
    if legacy_skills_dir.exists():
        shutil.rmtree(legacy_skills_dir)
    write_json(hooks_path, build_hooks(plugin_root, skills_dir))
    return {
        "runtime": "codex",
        "scope": scope,
        "files_written": [str(hooks_path), *skill_files],
        "notes": [
            *selection_warnings,
            "Installed Codex hooks.json.",
            "Codex hook compatibility follows Claude-style lifecycle hooks, but tool-hook coverage may vary by version.",
            "Some Codex installations may also require enabling hooks in user config.",
            "Session-start and status flows will auto-start agent-guard-fuse when the runtime binary is installed, "
            "so .agent/state.json and .agent/plan.yaml stay mounted under managed protection.",
            "Workflow skills were installed into Codex's native .codex/skills/<skill>/SKILL.md layout and "
            "injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def _clean_hooks(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return {}, 0
    return remove_marked_hook_entries(hooks, HOOK_MARKER)


def plan_uninstall(
    cwd: Path,
    home_dir: Path,
    scope: str,
    *,
    include_skills: bool = True,
) -> dict[str, Any]:
    """Plan removal of Codex hooks and optionally its installed skills."""
    hooks_path = hooks_file(scope, cwd, home_dir)
    changes: list[dict[str, str]] = []
    notes: list[str] = []
    if hooks_path.exists():
        config = read_json_if_exists(hooks_path, {})
        cleaned_hooks, removed = _clean_hooks(config)
        if removed:
            if cleaned_hooks:
                changes.append(hook_change("update", hooks_path, "Remove agent-guard hook entries from Codex hooks.json."))
                notes.append(json.dumps({"hooks": cleaned_hooks}, indent=2))
            else:
                changes.append(
                    hook_change("delete", hooks_path, "Delete hooks.json because it only contained agent-guard hooks.")
                )

    if include_skills:
        skills_dir = skills_install_dir(scope, cwd, home_dir)
        if skills_dir.exists():
            changes.append(skill_change(skills_dir))
        legacy_skills_dir = shared_skills_install_dir(scope, cwd, home_dir)
        if legacy_skills_dir.exists():
            changes.append(
                skill_change(legacy_skills_dir, "Delete the legacy agent-guard workflow skill bundle.")
            )
    return build_plan_result("codex", scope, changes, notes)


def apply_config_update(cwd: Path, home_dir: Path, scope: str) -> None:
    """Apply the Codex hook update described by an uninstall plan."""
    target_path = hooks_file(scope, cwd, home_dir)
    config = read_json_if_exists(target_path, {})
    cleaned_hooks, _ = _clean_hooks(config)
    if cleaned_hooks:
        write_json(target_path, {"hooks": cleaned_hooks})
    elif target_path.exists():
        target_path.unlink()


INTEGRATION = RuntimeIntegration(
    name="codex",
    install=install,
    plan_uninstall=plan_uninstall,
    apply_config_update=apply_config_update,
)
