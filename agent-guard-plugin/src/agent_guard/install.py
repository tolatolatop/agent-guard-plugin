from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

SUPPORTED_RUNTIMES = ("claude-code", "codex", "opencode")
SUPPORTED_SCOPES = ("project", "user")


def parse_flags(args: list[str]) -> dict[str, str | bool]:
    flags: dict[str, str | bool] = {}
    index = 0
    while index < len(args):
        current = args[index]
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


def uv_bridge_command(plugin_root: Path, action: str) -> str:
    return shell_command("uv", "run", "--project", str(plugin_root), "agent-guard-bridge", action)


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


def build_claude_hooks(plugin_root: Path) -> dict[str, Any]:
    return {
        "SessionStart": [
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "session-start")}],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "pre-write")}],
            },
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "pre-command")}],
            },
        ],
        "PostToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "post-command")}],
            }
        ],
        "Stop": [
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "stop")}],
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
    config["hooks"] = merge_claude_hooks(config.get("hooks", {}), build_claude_hooks(plugin_root), marker)
    write_json(config_path, config)
    return {
        "runtime": "claude-code",
        "scope": scope,
        "files_written": [str(config_path)],
        "notes": [
            "Installed Claude Code hooks into a settings JSON file.",
            "Claude Code passes hook payloads over stdin and can block PreToolUse or Stop hooks with exit code 2.",
        ],
    }


def build_codex_hooks(plugin_root: Path) -> dict[str, Any]:
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "session-start")}],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit|Bash",
                    "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "pre-dispatch")}],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "post-command")}],
                }
            ],
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": uv_bridge_command(plugin_root, "stop")}],
                }
            ],
        }
    }


def install_codex(cwd: Path, home_dir: Path, scope: str, plugin_root: Path) -> dict[str, Any]:
    hooks_path = codex_hooks_file(scope, cwd, home_dir)
    write_json(hooks_path, build_codex_hooks(plugin_root))
    return {
        "runtime": "codex",
        "scope": scope,
        "files_written": [str(hooks_path)],
        "notes": [
            "Installed Codex hooks.json.",
            "Codex hook compatibility follows Claude-style lifecycle hooks, but tool-hook coverage may vary by version.",
            "Some Codex installations may also require enabling hooks in user config.",
        ],
    }


def build_opencode_plugin_source(plugin_root: Path) -> str:
    command = uv_bridge_command(plugin_root, "opencode-event")
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
    plugin_path.write_text(build_opencode_plugin_source(plugin_root), encoding="utf-8")
    return {
        "runtime": "opencode",
        "scope": scope,
        "files_written": [str(plugin_path)],
        "notes": [
            "Installed an OpenCode JS loader that forwards plugin events to the Python bridge.",
            "All policy logic remains in Python; the JS file only marshals plugin events.",
            "OpenCode final-response gating remains best-effort because its plugin lifecycle differs from Claude Code and Codex.",
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
