"""OpenCode installation, removal, and event normalization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import BridgeAction, RuntimeIntegration, build_plan_result, hook_change, skill_change, uv_bridge_command
from .skills import install_native_skills_bundle


def skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return OpenCode's native skills directory."""
    if scope == "project":
        return cwd / ".opencode" / "skills"
    return home_dir / ".config" / "opencode" / "skills"


def plugin_file(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return the generated OpenCode loader path."""
    if scope == "project":
        return cwd / ".opencode" / "plugins" / "agent-guard.js"
    return home_dir / ".config" / "opencode" / "plugins" / "agent-guard.js"


def build_plugin_source(plugin_root: Path, skills_dir: Path) -> str:
    """Build the thin JavaScript loader that forwards events to Python."""
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

function sessionContextFrom(result) {{
  return result?.hookSpecificOutput?.additionalContext || result?.prompt_block || ""
}}

export const AgentGuardPlugin = async () => {{
  return {{
    event: async (input) => {{
      if (input?.event?.type === "session.created") {{
        runBridge({{ action: "session-start", payload: {{}} }})
      }}
    }},
    "experimental.chat.system.transform": async (_input, output) => {{
      const context = sessionContextFrom(runBridge({{ action: "session-start", payload: {{}} }}))
      if (context) {{
        output.system ||= []
        output.system.push(context)
      }}
    }},
    "tool.execute.before": async (input, output) => {{
      runBridge({{ action: "opencode-before", payload: {{ input, output }} }})
    }},
    "tool.execute.after": async (input, output) => {{
      runBridge({{ action: "opencode-after", payload: {{ input, output }} }})
    }},
  }}
}}
"""


def install(
    cwd: Path,
    home_dir: Path,
    scope: str,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Install the OpenCode integration."""
    target_plugin = plugin_file(scope, cwd, home_dir)
    target_plugin.parent.mkdir(parents=True, exist_ok=True)
    skills_dir = skills_install_dir(scope, cwd, home_dir)
    skill_files, selection_warnings = install_native_skills_bundle(
        skills_dir,
        plugin_root,
        include_matches,
        exclude_matches,
        empty_error="No OpenCode workflow skills were installed.",
        root_dir=cwd,
        workflow_id=workflow_id,
    )
    target_plugin.write_text(build_plugin_source(plugin_root, skills_dir), encoding="utf-8")
    return {
        "runtime": "opencode",
        "scope": scope,
        "files_written": [str(target_plugin), *skill_files],
        "notes": [
            *selection_warnings,
            "Installed an OpenCode JS loader that forwards plugin events to the Python bridge.",
            "All policy logic remains in Python; the JS file only marshals plugin events.",
            "OpenCode final-response gating remains best-effort because its plugin lifecycle differs from Claude Code and Codex.",
            "Session-start and status flows will auto-start agent-guard-fuse when the runtime binary is installed, "
            "so .agent/state.json and .agent/plan.yaml stay mounted under managed protection.",
            "Workflow skills were installed into OpenCode's native .opencode/skills/<skill>/SKILL.md layout and "
            "injected via AGENT_GUARD_SKILLS_DIR.",
        ],
    }


def plan_uninstall(
    cwd: Path,
    home_dir: Path,
    scope: str,
    *,
    include_skills: bool = True,
) -> dict[str, Any]:
    """Plan removal of the OpenCode loader and optionally its skills."""
    changes: list[dict[str, str]] = []
    target_plugin = plugin_file(scope, cwd, home_dir)
    if target_plugin.exists():
        changes.append(hook_change("delete", target_plugin, "Delete the generated OpenCode agent-guard loader."))
    skills_dir = skills_install_dir(scope, cwd, home_dir)
    if include_skills and skills_dir.exists():
        changes.append(skill_change(skills_dir))
    return build_plan_result("opencode", scope, changes)


def apply_config_update(cwd: Path, home_dir: Path, scope: str) -> None:
    """OpenCode uses a generated file, so it has no in-place update action."""


def _extract_apply_patch_paths(args: dict[str, Any]) -> list[str]:
    """Extract project-relative paths from OpenCode apply_patch text."""
    patch_text = args.get("patchText")
    if not isinstance(patch_text, str):
        return []

    paths: list[str] = []
    for line in patch_text.splitlines():
        for marker in ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "):
            if line.startswith(marker):
                path = line.removeprefix(marker).strip()
                if path:
                    paths.append(path)
                break
    return paths


def normalize_before_event(payload: dict[str, Any]) -> list[BridgeAction]:
    """Translate an OpenCode pre-tool event to generic bridge actions."""
    input_payload = payload.get("input")
    output_payload = payload.get("output")
    if isinstance(input_payload, dict):
        tool = input_payload.get("tool")
        if isinstance(output_payload, dict) and isinstance(output_payload.get("args"), dict):
            args = output_payload.get("args", {})
        else:
            args = input_payload.get("args", {})
    else:
        tool = payload.get("tool")
        args = payload.get("args", {})
    tool_input = args if isinstance(args, dict) else {}

    if tool == "apply_patch":
        return [
            BridgeAction("pre-write", {"tool_input": {"file_path": path}}, "opencode-before")
            for path in _extract_apply_patch_paths(tool_input)
        ]
    if tool in {"write", "edit", "patch"}:
        return [BridgeAction("pre-write", {"tool_input": tool_input}, "opencode-before")]
    if tool == "bash":
        return [BridgeAction("pre-command", {"tool_input": tool_input}, "opencode-before")]
    return []


def normalize_after_event(payload: dict[str, Any]) -> list[BridgeAction]:
    """Translate an OpenCode post-tool event to generic bridge actions."""
    input_payload = payload.get("input", {})
    output_payload = payload.get("output", {})
    if not isinstance(input_payload, dict) or input_payload.get("tool") != "bash":
        return []
    if isinstance(output_payload, dict) and isinstance(output_payload.get("args"), dict):
        args = output_payload.get("args", {})
        tool_response = output_payload.get("result", output_payload)
    else:
        args = input_payload.get("args", {})
        tool_response = output_payload
    if not isinstance(args, dict):
        args = {}
    bridge_payload = {
        "tool_input": args,
        "tool_response": tool_response if isinstance(tool_response, dict) else {},
    }
    return [BridgeAction("post-command", bridge_payload, "opencode-after")]


INTEGRATION = RuntimeIntegration(
    name="opencode",
    install=install,
    plan_uninstall=plan_uninstall,
    apply_config_update=apply_config_update,
)
