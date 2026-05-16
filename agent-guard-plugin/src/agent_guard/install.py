"""Runtime installation and uninstallation helpers for supported tools."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, TextIO

from .interactive import confirm_action, prompt_choice, prompt_text
from .workflow_spec import install_defaults as workflow_install_defaults

SUPPORTED_RUNTIMES = ("claude-code", "codex", "opencode")
SUPPORTED_SCOPES = ("project", "user")
SHORT_FLAG_ALIASES = {
    "-i": "interactive",
    "-r": "runtime",
    "-s": "scope",
}
MULTI_VALUE_FLAGS = {"match", "exclude-match"}


def _csv_patterns(value: str) -> list[str]:
    """Parse comma-separated interactive regex input."""
    return [part.strip() for part in value.split(",") if part.strip()]


def prompt_install_options(
    flags: dict[str, Any],
    input_stream: TextIO,
    output: TextIO,
) -> dict[str, Any]:
    """Prompt for install options when interactive mode is requested."""
    updated = dict(flags)
    default_runtime = str(updated.get("runtime") or "codex")
    default_scope = str(updated.get("scope") or "project")
    updated["runtime"] = prompt_choice("Runtime", list(SUPPORTED_RUNTIMES), input_stream, output, default_runtime)
    updated["scope"] = prompt_choice("Scope", list(SUPPORTED_SCOPES), input_stream, output, default_scope)

    match_default = ",".join(str(item) for item in updated.get("match", [])) if isinstance(updated.get("match"), list) else ""
    exclude_default = ",".join(str(item) for item in updated.get("exclude-match", [])) if isinstance(updated.get("exclude-match"), list) else ""
    include_raw = prompt_text("Include skill regexes (comma-separated, blank for defaults)", input_stream, output, default=match_default)
    exclude_raw = prompt_text("Exclude skill regexes (comma-separated, blank for defaults)", input_stream, output, default=exclude_default)

    include_patterns = _csv_patterns(include_raw)
    exclude_patterns = _csv_patterns(exclude_raw)
    if include_patterns:
        updated["match"] = include_patterns
    elif "match" in updated:
        updated.pop("match", None)
    if exclude_patterns:
        updated["exclude-match"] = exclude_patterns
    elif "exclude-match" in updated:
        updated.pop("exclude-match", None)
    updated["wizard"] = bool(updated.get("wizard")) or confirm_action(
        "Run setup wizard after install?",
        input_stream,
        output,
    )
    return updated


def prompt_missing_install_axes(
    flags: dict[str, Any],
    input_stream: TextIO,
    output: TextIO,
) -> dict[str, Any]:
    """Prompt only for missing runtime and scope install axes."""
    updated = dict(flags)
    runtime = updated.get("runtime")
    scope = updated.get("scope")
    prompted = False

    if runtime not in SUPPORTED_RUNTIMES:
        updated["runtime"] = prompt_choice("Runtime", list(SUPPORTED_RUNTIMES), input_stream, output, default="codex")
        prompted = True
    if scope not in SUPPORTED_SCOPES:
        updated["scope"] = prompt_choice("Scope", list(SUPPORTED_SCOPES), input_stream, output, default="project")
        prompted = True
    if prompted and "wizard" not in updated:
        updated["wizard"] = confirm_action("Run setup wizard after install?", input_stream, output)
    return updated


def parse_flags(args: list[str]) -> dict[str, Any]:
    """Parse flags."""
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


def read_json_if_exists(file_path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    """Read json if exists."""
    if not file_path.exists():
        return fallback
    return json.loads(file_path.read_text(encoding="utf-8"))


def write_json(file_path: Path, value: dict[str, Any]) -> None:
    """Write json."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def shell_command(*parts: str) -> str:
    """Shell command."""
    return " ".join(shlex.quote(part) for part in parts)


def shell_assignment(key: str, value: str) -> str:
    """Shell assignment."""
    return f"{key}={shlex.quote(value)}"


def shared_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Shared skills install dir."""
    return cwd / ".agent-guard" / "skills" if scope == "project" else home_dir / ".agent-guard" / "skills"


def claude_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Claude skills install dir."""
    return cwd / ".claude" / "skills" if scope == "project" else home_dir / ".claude" / "skills"


def opencode_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Opencode skills install dir."""
    if scope == "project":
        return cwd / ".opencode" / "skills"
    return home_dir / ".config" / "opencode" / "skills"


def packaged_skills_dir() -> Path:
    """Packaged skills dir."""
    package_dir = Path(__file__).resolve().parent
    bundled_dir = package_dir / "_bundled_skills"
    if bundled_dir.exists() and any(bundled_dir.glob("*.md")):
        return bundled_dir

    repo_root = package_dir.parents[1]
    docs_dir = repo_root / "docs" / "skills"
    if docs_dir.exists() and any(docs_dir.glob("*.md")):
        return docs_dir

    return bundled_dir


def source_skills_dir(plugin_root: Path) -> Path:
    """Source skills dir."""
    candidates = [
        plugin_root / "docs" / "skills",
        packaged_skills_dir(),
    ]
    for candidate in candidates:
        if candidate.exists() and any(candidate.glob("*.md")):
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise RuntimeError(f"Could not locate bundled workflow skills. Searched: {searched}")


def skill_slug_from_source(source_file: Path) -> str:
    """Skill slug from source."""
    return source_file.stem


def _skill_match_haystack(source_file: Path) -> str:
    """Build the searchable text for skill selection."""
    return "\n".join(
        [
            skill_slug_from_source(source_file),
            source_file.name,
        ]
    )


def _compile_matchers(patterns: list[str], label: str) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error as exc:
            raise RuntimeError(f"Invalid {label} regex {pattern!r}: {exc}") from exc
    return compiled


def selected_skill_sources(plugin_root: Path, include_matches: list[str] | None = None, exclude_matches: list[str] | None = None) -> list[Path]:
    """Select skill sources by positive and negative regex matches."""
    source_files = sorted(source_skills_dir(plugin_root).glob("*.md"))
    include_patterns = _compile_matchers(include_matches or [], "--match")
    exclude_patterns = _compile_matchers(exclude_matches or [], "--exclude-match")

    selected: list[Path] = []
    for source_file in source_files:
        haystack = _skill_match_haystack(source_file)
        if include_patterns and not any(pattern.search(haystack) for pattern in include_patterns):
            continue
        if exclude_patterns and any(pattern.search(haystack) for pattern in exclude_patterns):
            continue
        selected.append(source_file)
    return selected


def resolve_skill_filters(
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> tuple[list[str], list[str], str]:
    """Resolve install skill filters from CLI flags or workflow defaults."""
    cli_include = list(include_matches or [])
    cli_exclude = list(exclude_matches or [])
    if cli_include or cli_exclude:
        return cli_include, cli_exclude, "cli"

    defaults = workflow_install_defaults()
    return list(defaults.get("skill_match", [])), list(defaults.get("skill_exclude_match", [])), "workflow"


def install_selection_warning(source: str, include_matches: list[str], exclude_matches: list[str]) -> str:
    """Build a warning when workflow-provided selection matches nothing."""
    details: list[str] = []
    if include_matches:
        details.append(f"match={include_matches!r}")
    if exclude_matches:
        details.append(f"exclude_match={exclude_matches!r}")
    rendered = ", ".join(details) if details else "no filters"
    return (
        "Workflow skill selection matched no installable skills; "
        f"ignoring {rendered} from {source} defaults and falling back to full install."
    )


def selected_skill_sources_with_fallback(
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> tuple[list[Path], list[str]]:
    """Select skills, warning and falling back to full install for empty workflow defaults."""
    resolved_include, resolved_exclude, source = resolve_skill_filters(include_matches, exclude_matches)
    selected = selected_skill_sources(plugin_root, resolved_include, resolved_exclude)
    if selected or source != "workflow" or (not resolved_include and not resolved_exclude):
        return selected, []
    return sorted(source_skills_dir(plugin_root).glob("*.md")), [install_selection_warning(source, resolved_include, resolved_exclude)]


def install_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Install skills bundle."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    selected_sources, warnings = selected_skill_sources_with_fallback(plugin_root, include_matches, exclude_matches)
    for source_file in selected_sources:
        target_file = target_dir / source_file.name
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No workflow skills were installed.")
    return written_files, warnings


def install_claude_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Install claude skills bundle."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    selected_sources, warnings = selected_skill_sources_with_fallback(plugin_root, include_matches, exclude_matches)
    for source_file in selected_sources:
        legacy_target = target_dir / source_file.name
        if legacy_target.exists():
            legacy_target.unlink()
        target_file = target_dir / skill_slug_from_source(source_file) / "SKILL.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No Claude workflow skills were installed.")
    return written_files, warnings


def install_opencode_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Install opencode skills bundle."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    selected_sources, warnings = selected_skill_sources_with_fallback(plugin_root, include_matches, exclude_matches)
    for source_file in selected_sources:
        legacy_target = target_dir / source_file.name
        if legacy_target.exists():
            legacy_target.unlink()
        target_file = target_dir / skill_slug_from_source(source_file) / "SKILL.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No OpenCode workflow skills were installed.")
    return written_files, warnings


def uv_bridge_command(plugin_root: Path, action: str, skills_dir: Path) -> str:
    """Uv bridge command."""
    return " ".join(
        [
            shell_assignment("AGENT_GUARD_SKILLS_DIR", str(skills_dir)),
            shell_command("uv", "run", "--project", str(plugin_root), "agent-guard-bridge", action),
        ]
    )


def claude_config_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Claude config file."""
    return cwd / ".claude" / "settings.local.json" if scope == "project" else home_dir / ".claude" / "settings.json"


def codex_hooks_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Codex hooks file."""
    return cwd / ".codex" / "hooks.json" if scope == "project" else home_dir / ".codex" / "hooks.json"


def opencode_plugin_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Opencode plugin file."""
    if scope == "project":
        return cwd / ".opencode" / "plugins" / "agent-guard.js"
    return home_dir / ".config" / "opencode" / "plugins" / "agent-guard.js"


def dedupe_hook_entries(entries: list[dict[str, Any]], marker: str) -> list[dict[str, Any]]:
    """Deduplicate hook entries."""
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
    """Build claude hooks."""
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
    """Merge claude hooks."""
    merged = dict(existing_hooks)
    for event_name, entries in new_hooks.items():
        existing_entries = merged.get(event_name, [])
        if not isinstance(existing_entries, list):
            existing_entries = []
        merged[event_name] = [*dedupe_hook_entries(existing_entries, marker), *entries]
    return merged


def install_claude_code(
    cwd: Path,
    home_dir: Path,
    scope: str,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> dict[str, Any]:
    """Install claude code."""
    config_path = claude_config_file(scope, cwd, home_dir)
    config = read_json_if_exists(config_path, {})
    marker = "agent-guard-bridge"
    skills_dir = claude_skills_install_dir(scope, cwd, home_dir)
    skill_files, selection_warnings = install_claude_skills_bundle(skills_dir, plugin_root, include_matches, exclude_matches)
    config["hooks"] = merge_claude_hooks(config.get("hooks", {}), build_claude_hooks(plugin_root, skills_dir), marker)
    write_json(config_path, config)
    return {
        "runtime": "claude-code",
        "scope": scope,
        "files_written": [str(config_path), *skill_files],
        "notes": [
            *selection_warnings,
            "Installed Claude Code hooks into a settings JSON file.",
            "Claude Code passes hook payloads over stdin and can block PreToolUse or Stop hooks with exit code 2.",
            "Session-start and status flows will auto-start agent-guard-fuse when the runtime binary is installed, so .agent/state.json and .agent/plan.yaml stay mounted under managed protection.",
            "Workflow skills were installed into Claude's native .claude/skills/<skill>/SKILL.md layout and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def build_codex_hooks(plugin_root: Path, skills_dir: Path) -> dict[str, Any]:
    """Build codex hooks."""
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


def install_codex(
    cwd: Path,
    home_dir: Path,
    scope: str,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> dict[str, Any]:
    """Install codex."""
    hooks_path = codex_hooks_file(scope, cwd, home_dir)
    skills_dir = shared_skills_install_dir(scope, cwd, home_dir)
    skill_files, selection_warnings = install_skills_bundle(skills_dir, plugin_root, include_matches, exclude_matches)
    write_json(hooks_path, build_codex_hooks(plugin_root, skills_dir))
    return {
        "runtime": "codex",
        "scope": scope,
        "files_written": [str(hooks_path), *skill_files],
        "notes": [
            *selection_warnings,
            "Installed Codex hooks.json.",
            "Codex hook compatibility follows Claude-style lifecycle hooks, but tool-hook coverage may vary by version.",
            "Some Codex installations may also require enabling hooks in user config.",
            "Session-start and status flows will auto-start agent-guard-fuse when the runtime binary is installed, so .agent/state.json and .agent/plan.yaml stay mounted under managed protection.",
            "Workflow skills were copied into a local agent-guard skills directory and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def build_opencode_plugin_source(plugin_root: Path, skills_dir: Path) -> str:
    """Build opencode plugin source."""
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


def install_opencode(
    cwd: Path,
    home_dir: Path,
    scope: str,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> dict[str, Any]:
    """Install opencode."""
    plugin_path = opencode_plugin_file(scope, cwd, home_dir)
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    skills_dir = opencode_skills_install_dir(scope, cwd, home_dir)
    skill_files, selection_warnings = install_opencode_skills_bundle(skills_dir, plugin_root, include_matches, exclude_matches)
    plugin_path.write_text(build_opencode_plugin_source(plugin_root, skills_dir), encoding="utf-8")
    return {
        "runtime": "opencode",
        "scope": scope,
        "files_written": [str(plugin_path), *skill_files],
        "notes": [
            *selection_warnings,
            "Installed an OpenCode JS loader that forwards plugin events to the Python bridge.",
            "All policy logic remains in Python; the JS file only marshals plugin events.",
            "OpenCode final-response gating remains best-effort because its plugin lifecycle differs from Claude Code and Codex.",
            "Session-start and status flows will auto-start agent-guard-fuse when the runtime binary is installed, so .agent/state.json and .agent/plan.yaml stay mounted under managed protection.",
            "Workflow skills were installed into OpenCode's native .opencode/skills/<skill>/SKILL.md layout and injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def install_runtime(
    argv: list[str],
    cwd: Path,
    home_dir: Path | None,
    plugin_root: Path,
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
) -> dict[str, Any]:
    """Install runtime."""
    flags = parse_flags(argv)
    install_input = input_stream or sys.stdin
    install_output = output or sys.stdout
    if bool(flags.get("interactive")):
        flags = prompt_install_options(flags, install_input, install_output)
    else:
        flags = prompt_missing_install_axes(flags, install_input, install_output)
    runtime = flags.get("runtime")
    scope = flags.get("scope", "project")
    if runtime not in SUPPORTED_RUNTIMES:
        raise RuntimeError(f"Missing or unsupported --runtime. Expected one of: {', '.join(SUPPORTED_RUNTIMES)}")
    if scope not in SUPPORTED_SCOPES:
        raise RuntimeError(f"Unsupported --scope. Expected one of: {', '.join(SUPPORTED_SCOPES)}")

    resolved_home = home_dir or Path(os.path.expanduser("~"))
    include_matches = [str(item) for item in flags.get("match", [])] if isinstance(flags.get("match"), list) else []
    exclude_matches = [str(item) for item in flags.get("exclude-match", [])] if isinstance(flags.get("exclude-match"), list) else []
    run_wizard_after_install = bool(flags.get("wizard"))
    if runtime == "claude-code":
        result = install_claude_code(cwd, resolved_home, str(scope), plugin_root, include_matches, exclude_matches)
    elif runtime == "codex":
        result = install_codex(cwd, resolved_home, str(scope), plugin_root, include_matches, exclude_matches)
    else:
        result = install_opencode(cwd, resolved_home, str(scope), plugin_root, include_matches, exclude_matches)

    if run_wizard_after_install:
        from .wizard import run_wizard

        result["wizard"] = run_wizard(cwd, install_input, install_output)
    else:
        result["wizard"] = None
    return result


def _hook_matches_marker(hook: Any, marker: str) -> bool:
    """Internal helper for hook matches marker."""
    return isinstance(hook, dict) and marker in str(hook.get("command", ""))


def _remove_marked_hook_entries(hooks: dict[str, Any], marker: str) -> tuple[dict[str, Any], int]:
    """Internal helper for remove marked hook entries."""
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
    """Internal helper for cleanup empty dirs."""
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
    """Internal helper for build plan result."""
    return {
        "runtime": runtime,
        "scope": scope,
        "changes": changes,
        "notes": notes or [],
    }


def plan_uninstall_claude_code(cwd: Path, home_dir: Path, scope: str) -> dict[str, Any]:
    """Plan uninstall claude code."""
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
    """Plan uninstall codex."""
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
    """Plan uninstall opencode."""
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
    """Plan uninstall runtime."""
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
    """Internal helper for render uninstall preview."""
    output.write("The following changes will be applied:\n")
    for change in plan["changes"]:
        output.write(f"- {change['action']}: {change['path']}\n")
        output.write(f"  {change['details']}\n")


def _confirm_uninstall(output: TextIO, input_stream: TextIO) -> bool:
    """Internal helper for confirm uninstall."""
    return confirm_action("Proceed with uninstall?", input_stream, output)


def apply_uninstall_plan(plan: dict[str, Any], cwd: Path, home_dir: Path | None) -> dict[str, Any]:
    """Apply uninstall plan."""
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
    """Uninstall runtime."""
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
