"""Shared contracts and helpers for runtime integrations."""
from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


InstallRuntime = Callable[
    [Path, Path, str, Path, list[str] | None, list[str] | None, str | None],
    dict[str, Any],
]
PlanUninstall = Callable[..., dict[str, Any]]
ApplyConfigUpdate = Callable[[Path, Path, str], None]


@dataclass(frozen=True)
class RuntimeIntegration:
    """Operations owned by one supported agent runtime."""

    name: str
    install: InstallRuntime
    plan_uninstall: PlanUninstall
    apply_config_update: ApplyConfigUpdate


@dataclass(frozen=True)
class BridgeAction:
    """A runtime event normalized to one generic bridge operation."""

    action: str
    payload: dict[str, Any]
    source: str


def read_json_if_exists(file_path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    """Read a JSON object, returning ``fallback`` when the file is absent."""
    if not file_path.exists():
        return fallback
    return json.loads(file_path.read_text(encoding="utf-8"))


def write_json(file_path: Path, value: dict[str, Any]) -> None:
    """Write a consistently formatted JSON object."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def shell_command(*parts: str) -> str:
    """Render a shell command with every argument quoted."""
    return " ".join(shlex.quote(part) for part in parts)


def shell_assignment(key: str, value: str) -> str:
    """Render a quoted shell environment assignment."""
    return f"{key}={shlex.quote(value)}"


def uv_bridge_command(plugin_root: Path, action: str, skills_dir: Path) -> str:
    """Build the command used by runtime hooks to enter the Python bridge."""
    return " ".join(
        [
            shell_assignment("AGENT_GUARD_SKILLS_DIR", str(skills_dir)),
            shell_command("uv", "run", "--project", str(plugin_root), "agent-guard-bridge", action),
        ]
    )


def dedupe_hook_entries(entries: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    """Remove hook groups containing a command owned by agent-guard."""
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            filtered.append(entry)
            continue
        if any(isinstance(hook, dict) and marker in str(hook.get("command", "")) for hook in hooks):
            continue
        filtered.append(entry)
    return filtered


def _hook_matches_marker(hook: Any, marker: str) -> bool:
    return isinstance(hook, dict) and marker in str(hook.get("command", ""))


def remove_marked_hook_entries(hooks: dict[str, Any], marker: str) -> tuple[dict[str, Any], int]:
    """Remove individual marked commands while preserving unrelated hooks."""
    cleaned: dict[str, Any] = {}
    removed = 0

    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            cleaned[event_name] = entries
            continue

        next_entries: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_hooks = entry.get("hooks")
            if not isinstance(entry_hooks, list):
                next_entries.append(entry)
                continue
            filtered_hooks = [hook for hook in entry_hooks if not _hook_matches_marker(hook, marker)]
            removed += len(entry_hooks) - len(filtered_hooks)
            if filtered_hooks:
                next_entries.append({**entry, "hooks": filtered_hooks})
        if next_entries:
            cleaned[event_name] = next_entries

    return cleaned, removed


def build_plan_result(
    runtime: str,
    scope: str,
    changes: list[dict[str, str]],
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Build the stable public shape returned by uninstall planning."""
    return {
        "runtime": runtime,
        "scope": scope,
        "changes": changes,
        "notes": notes or [],
    }


def hook_change(action: str, path: Path, details: str) -> dict[str, str]:
    """Describe a runtime hook/configuration change."""
    return {
        "action": action,
        "path": str(path),
        "details": details,
        "component": "hooks",
    }


def skill_change(path: Path, details: str = "Delete the installed workflow skill bundle.") -> dict[str, str]:
    """Describe removal of an installed skill bundle."""
    return {
        "action": "delete-tree",
        "path": str(path),
        "details": details,
        "component": "skills",
    }


def cleanup_empty_dirs(start_dir: Path, stop_dir: Path) -> None:
    """Remove empty parents up to, but not including, ``stop_dir``."""
    current = start_dir
    while current != stop_dir:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
