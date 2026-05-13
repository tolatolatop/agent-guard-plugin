from __future__ import annotations

import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any, TextIO

from .interactive import confirm_action

SUPPORTED_RUNTIMES = ("claude-code", "codex", "opencode")
SUPPORTED_SCOPES = ("project", "user")
SHORT_FLAG_ALIASES = {
    "-r": "runtime",
    "-s": "scope",
}


def parse_flags(args: list[str]) -> dict[str, str | bool]:
    flags: dict[str, str | bool] = {}
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
        flags[key] = next_value
        index += 2
    return flags


def read_json_if_exists(file_path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not file_path.exists():
        return fallback
    return json.loads(file_path.read_text(encoding="utf-8"))


def write_json(file_path: Path, value: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def shell_command(*parts: str) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def shell_assignment(key: str, value: str) -> str:
    return f"{key}={shlex.quote(value)}"


def shared_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    return cwd / ".agent-guard" / "skills" if scope == "project" else home_dir / ".agent-guard" / "skills"


def claude_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    return cwd / ".claude" / "skills" if scope == "project" else home_dir / ".claude" / "skills"


def opencode_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    if scope == "project":
        return cwd / ".opencode" / "skills"
    return home_dir / ".config" / "opencode" / "skills"


def packaged_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "_bundled_skills"


def source_skills_dir(plugin_root: Path) -> Path:
    candidates = [
        packaged_skills_dir(),
        plugin_root / "docs" / "skills",
    ]
    for candidate in candidates:
        if candidate.exists() and any(candidate.glob("*.md")):
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise RuntimeError(f"Could not locate bundled workflow skills. Searched: {searched}")


def skill_slug_from_source(source_file: Path) -> str:
    return source_file.stem


def install_skills_bundle(target_dir: Path, plugin_root: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    for source_file in sorted(source_skills_dir(plugin_root).glob("*.md")):
        target_file = target_dir / source_file.name
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No workflow skills were installed.")
    return written_files


def install_claude_skills_bundle(target_dir: Path, plugin_root: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    for source_file in sorted(source_skills_dir(plugin_root).glob("*.md")):
        legacy_target = target_dir / source_file.name
        if legacy_target.exists():
            legacy_target.unlink()
        target_file = target_dir / skill_slug_from_source(source_file) / "SKILL.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No Claude workflow skills were installed.")
    return written_files


def install_opencode_skills_bundle(target_dir: Path, plugin_root: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    for source_file in sorted(source_skills_dir(plugin_root).glob("*.md")):
        legacy_target = target_dir / source_file.name
        if legacy_target.exists():
            legacy_target.unlink()
        target_file = target_dir / skill_slug_from_source(source_file) / "SKILL.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No OpenCode workflow skills were installed.")
    return written_files


def uv_bridge_command(plugin_root: Path, action: str, skills_dir: Path) -> str:
    return " ".join(
        [
            shell_assignment("AGENT_GUARD_SKILLS_DIR", str(skills_dir)),
            shell_command("uv", "run", "--project", str(plugin_root), "agent-guard-bridge", action),
        ]
    )


def claude_config_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    return cwd / ".claude" / "settings.local.json" if scope == "project" else home_dir / ".claude" / "settings.json"


def codex_hooks_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    return cwd / ".codex" / "hooks.json" if scope == "project" else home_dir / ".codex" / "hooks.json"


def opencode_plugin_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    if scope == "project":
        return cwd / ".opencode" / "plugins" / "agent-guard.js"
    return home_dir / ".config" / "opencode" / "plugins" / "agent-guard.js"


def dedupe_hook_entries(entries: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
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


def build_claude_hooks(plugin_root: Path, skills_dir: Path) -> dict[str, Any]:
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


def merge_claude_hooks(existing_hooks: dict[str, Any], new_hooks: dict[str, Any], marker: str) -> dict[str, Any]:
    merged = dict(existing_hooks)
    for event_name, entries in new_hooks.items():
        existing_entries = merged.get(event_name, [])
        if not isinstance(existing_entries, list):
            existing_entries = []
        merged[event_name] = [*dedupe_hook_entries(existing_entries, marker), *entries]
    return merged


def install_claude_code(cwd: Path, home_dir: Path, scope: str, plugin_root: Path) -> dict[str, Any]:
    config_path = claude_config_file(scope, cwd, home_dir)
    config = read_json_if_exists(config_path, {})
    marker = "agent-guard-bridge"
    skills_dir = claude_skills_install_dir(scope, cwd, home_dir)
    skill_files = install_claude_skills_bundle(skills_dir, plugin_root)
    config["hooks"] = merge_claude_hooks(config.get("hooks", {}), build_claude_hooks(plugin_root, skills_dir), marker)
    write_json(config_path, config)
    return {
        "runtime": "claude-code",
        "scope": scope,
        "files_written": [str(config_path), *skill_files],
        "notes": [
            "Installed Claude Code hooks into a settings JSON file.",
            "Claude Code passes hook payloads over stdin and can block PreToolUse or Stop hooks with exit code 2.",
            "Workflow skills were installed into Claude's native .claude/skills/<skill>/SKILL.md layout and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def build_codex_hooks(plugin_root: Path, skills_dir: Path) -> dict[str, Any]:
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


def install_codex(cwd: Path, home_dir: Path, scope: str, plugin_root: Path) -> dict[str, Any]:
    hooks_path = codex_hooks_file(scope, cwd, home_dir)
    skills_dir = shared_skills_install_dir(scope, cwd, home_dir)
    skill_files = install_skills_bundle(skills_dir, plugin_root)
    write_json(hooks_path, build_codex_hooks(plugin_root, skills_dir))
    return {
        "runtime": "codex",
        "scope": scope,
        "files_written": [str(hooks_path), *skill_files],
        "notes": [
            "Installed Codex hooks.json.",
            "Codex hook compatibility follows Claude-style lifecycle hooks, but tool-hook coverage may vary by version.",
            "Some Codex installations may also require enabling hooks in user config.",
            "Workflow skills were copied into a local agent-guard skills directory and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def build_opencode_plugin_source(plugin_root: Path, skills_dir: Path) -> str:
    command = uv_bridge_command(plugin_root, "opencode-event", skills_dir)
    return f"""import {{ spawnSync }} from "node:child_process"

const BRIDGE_COMMAND = {json.dumps(command)}

function runBridge(payload) {{
  const result = spawnSync("sh", ["-lc", BRIDGE_COMMAND], {{
    cwd: process.cwd(),
    encoding: "utf8",
    input: JSON.stringify(payload),
  }})

  const stdout = (result.stdout || "").trim() || "{{}}"
  let parsed
  try {{
    parsed = JSON.parse(stdout)
  }} catch {{
    parsed = {{ raw: stdout }}
  }}

  if (result.status !== 0) {{
    const reason = parsed.reason || (parsed.reasons || []).join("; ") || parsed.error || result.stderr || "agent-guard rejected the action"
    throw new Error(reason)
  }}

  return parsed
}}

export const AgentGuardPlugin = async () => {{
  return {{
    "session.created": async () => {{
      runBridge({{ action: "session-start", payload: {{}} }})
    }},
    "tool.execute.before": async (input) => {{
      runBridge({{ action: "opencode-before", payload: input }})
    }},
    "tool.execute.after": async (input, output) => {{
      runBridge({{ action: "opencode-after", payload: {{ input, output }} }})
    }},
  }}
}}
"""


def install_opencode(cwd: Path, home_dir: Path, scope: str, plugin_root: Path) -> dict[str, Any]:
    plugin_path = opencode_plugin_file(scope, cwd, home_dir)
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    skills_dir = opencode_skills_install_dir(scope, cwd, home_dir)
    skill_files = install_opencode_skills_bundle(skills_dir, plugin_root)
    plugin_path.write_text(build_opencode_plugin_source(plugin_root, skills_dir), encoding="utf-8")
    return {
        "runtime": "opencode",
        "scope": scope,
        "files_written": [str(plugin_path), *skill_files],
        "notes": [
            "Installed an OpenCode JS loader that forwards plugin events to the Python bridge.",
            "All policy logic remains in Python; the JS file only marshals plugin events.",
            "OpenCode final-response gating remains best-effort because its plugin lifecycle differs from Claude Code and Codex.",
            "Workflow skills were installed into OpenCode's native .opencode/skills/<skill>/SKILL.md layout and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def install_runtime(argv: list[str], cwd: Path, home_dir: Path | None, plugin_root: Path) -> dict[str, Any]:
    flags = parse_flags(argv)
    runtime = flags.get("runtime")
    scope = flags.get("scope", "project")
    if runtime not in SUPPORTED_RUNTIMES:
        raise RuntimeError(f"Missing or unsupported --runtime. Expected one of: {', '.join(SUPPORTED_RUNTIMES)}")
    if scope not in SUPPORTED_SCOPES:
        raise RuntimeError(f"Unsupported --scope. Expected one of: {', '.join(SUPPORTED_SCOPES)}")

    resolved_home = home_dir or Path(os.path.expanduser("~"))
    if runtime == "claude-code":
        return install_claude_code(cwd, resolved_home, str(scope), plugin_root)
    if runtime == "codex":
        return install_codex(cwd, resolved_home, str(scope), plugin_root)
    return install_opencode(cwd, resolved_home, str(scope), plugin_root)


def _hook_matches_marker(hook: Any, marker: str) -> bool:
    return isinstance(hook, dict) and marker in str(hook.get("command", ""))


def _remove_marked_hook_entries(hooks: dict[str, Any], marker: str) -> tuple[dict[str, Any], int]:
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


def _cleanup_empty_dirs(start_dir: Path, stop_dir: Path) -> None:
    current = start_dir
    while True:
        if current == stop_dir:
            break
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _build_plan_result(runtime: str, scope: str, changes: list[dict[str, str]], notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "runtime": runtime,
        "scope": scope,
        "changes": changes,
        "notes": notes or [],
    }


def plan_uninstall_claude_code(cwd: Path, home_dir: Path, scope: str) -> dict[str, Any]:
    config_path = claude_config_file(scope, cwd, home_dir)
    if not config_path.exists():
        return _build_plan_result("claude-code", scope, [])

    config = read_json_if_exists(config_path, {})
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return _build_plan_result("claude-code", scope, [])

    cleaned_hooks, removed = _remove_marked_hook_entries(hooks, "agent-guard-bridge")
    if removed == 0:
        return _build_plan_result("claude-code", scope, [])

    next_config = dict(config)
    if cleaned_hooks:
        next_config["hooks"] = cleaned_hooks
    else:
        next_config.pop("hooks", None)

    if next_config:
        return _build_plan_result(
            "claude-code",
            scope,
            [
                {
                    "action": "update",
                    "path": str(config_path),
                    "details": "Remove agent-guard hook entries from Claude Code settings.",
                }
            ],
            notes=[json.dumps(next_config, indent=2)],
        )

    return _build_plan_result(
        "claude-code",
        scope,
        [
            {
                "action": "delete",
                "path": str(config_path),
                "details": "Delete the Claude Code settings file because it only contained agent-guard hooks.",
            }
        ],
    )


def plan_uninstall_codex(cwd: Path, home_dir: Path, scope: str) -> dict[str, Any]:
    hooks_path = codex_hooks_file(scope, cwd, home_dir)
    if not hooks_path.exists():
        return _build_plan_result("codex", scope, [])

    config = read_json_if_exists(hooks_path, {})
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return _build_plan_result("codex", scope, [])

    cleaned_hooks, removed = _remove_marked_hook_entries(hooks, "agent-guard-bridge")
    if removed == 0:
        return _build_plan_result("codex", scope, [])

    if cleaned_hooks:
        return _build_plan_result(
            "codex",
            scope,
            [
                {
                    "action": "update",
                    "path": str(hooks_path),
                    "details": "Remove agent-guard hook entries from Codex hooks.json.",
                }
            ],
            notes=[json.dumps({"hooks": cleaned_hooks}, indent=2)],
        )

    return _build_plan_result(
        "codex",
        scope,
        [
            {
                "action": "delete",
                "path": str(hooks_path),
                "details": "Delete hooks.json because it only contained agent-guard hooks.",
            }
        ],
    )


def plan_uninstall_opencode(cwd: Path, home_dir: Path, scope: str) -> dict[str, Any]:
    plugin_path = opencode_plugin_file(scope, cwd, home_dir)
    skills_dir = opencode_skills_install_dir(scope, cwd, home_dir)
    changes: list[dict[str, str]] = []

    if plugin_path.exists():
        changes.append(
            {
                "action": "delete",
                "path": str(plugin_path),
                "details": "Delete the generated OpenCode agent-guard loader.",
            }
        )

    if skills_dir.exists():
        changes.append(
            {
                "action": "delete-tree",
                "path": str(skills_dir),
                "details": "Delete the installed workflow skill bundle.",
            }
        )

    if not changes:
        return _build_plan_result("opencode", scope, [])
    return _build_plan_result("opencode", scope, changes)


def plan_uninstall_runtime(argv: list[str], cwd: Path, home_dir: Path | None) -> dict[str, Any]:
    flags = parse_flags(argv)
    runtime = flags.get("runtime")
    scope = flags.get("scope", "project")
    if runtime not in SUPPORTED_RUNTIMES:
        raise RuntimeError(f"Missing or unsupported --runtime. Expected one of: {', '.join(SUPPORTED_RUNTIMES)}")
    if scope not in SUPPORTED_SCOPES:
        raise RuntimeError(f"Unsupported --scope. Expected one of: {', '.join(SUPPORTED_SCOPES)}")

    resolved_home = home_dir or Path(os.path.expanduser("~"))
    if runtime == "claude-code":
        plan = plan_uninstall_claude_code(cwd, resolved_home, str(scope))
        skills_dir = claude_skills_install_dir(str(scope), cwd, resolved_home)
    elif runtime == "codex":
        plan = plan_uninstall_codex(cwd, resolved_home, str(scope))
        skills_dir = shared_skills_install_dir(str(scope), cwd, resolved_home)
    else:
        plan = plan_uninstall_opencode(cwd, resolved_home, str(scope))
        skills_dir = opencode_skills_install_dir(str(scope), cwd, resolved_home)
    if skills_dir.exists():
        plan["changes"].append(
            {
                "action": "delete-tree",
                "path": str(skills_dir),
                "details": "Delete the installed workflow skill bundle.",
            }
        )
    return plan


def _render_uninstall_preview(plan: dict[str, Any], output: TextIO) -> None:
    output.write("The following changes will be applied:\n")
    for change in plan["changes"]:
        output.write(f"- {change['action']}: {change['path']}\n")
        output.write(f"  {change['details']}\n")


def _confirm_uninstall(output: TextIO, input_stream: TextIO) -> bool:
    return confirm_action("Proceed with uninstall?", input_stream, output)


def apply_uninstall_plan(plan: dict[str, Any], cwd: Path, home_dir: Path | None) -> dict[str, Any]:
    scope = plan["scope"]
    resolved_home = home_dir or Path(os.path.expanduser("~"))

    for change in plan["changes"]:
        file_path = Path(change["path"])
        if change["action"] == "delete":
            if file_path.exists():
                file_path.unlink()
                if file_path.parent.name == ".claude":
                    _cleanup_empty_dirs(file_path.parent, resolved_home if scope == "user" else cwd)
                elif file_path.parent.name == ".codex":
                    _cleanup_empty_dirs(file_path.parent, resolved_home if scope == "user" else cwd)
                elif file_path.parent.name == "plugins":
                    stop_dir = resolved_home / ".config" if scope == "user" else cwd
                    _cleanup_empty_dirs(file_path.parent, stop_dir)
        elif change["action"] == "delete-tree":
            if file_path.exists():
                shutil.rmtree(file_path)
        elif change["action"] == "update":
            if plan["runtime"] == "claude-code":
                target_path = claude_config_file(scope, cwd, resolved_home)
                config = read_json_if_exists(target_path, {})
                cleaned_hooks, _ = _remove_marked_hook_entries(config.get("hooks", {}), "agent-guard-bridge")
                next_config = dict(config)
                if cleaned_hooks:
                    next_config["hooks"] = cleaned_hooks
                else:
                    next_config.pop("hooks", None)
                if next_config:
                    write_json(target_path, next_config)
                elif target_path.exists():
                    target_path.unlink()
            elif plan["runtime"] == "codex":
                target_path = codex_hooks_file(scope, cwd, resolved_home)
                config = read_json_if_exists(target_path, {})
                cleaned_hooks, _ = _remove_marked_hook_entries(config.get("hooks", {}), "agent-guard-bridge")
                if cleaned_hooks:
                    write_json(target_path, {"hooks": cleaned_hooks})
                elif target_path.exists():
                    target_path.unlink()

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
    flags = parse_flags(argv)
    assume_yes = bool(flags.get("yes"))
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
    if not assume_yes and not _confirm_uninstall(output, input_stream):
        return {
            "runtime": plan["runtime"],
            "scope": plan["scope"],
            "changes_applied": [],
            "cancelled": True,
            "message": "Uninstall cancelled.",
        }

    return apply_uninstall_plan(plan, cwd, home_dir)
