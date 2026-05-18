"""Hook bridge for Claude, Codex, and OpenCode runtime integrations."""
from __future__ import annotations

import json
import sys
import traceback
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from .cli import run_command
from .events import append_event
from .state import artifacts_dir, ensure_agent_files, load_state
from .workflow_spec import (
    canonical_completion_ready_stage,
    canonical_expected_failure_stage,
    canonical_stage_stop_allowed,
    canonical_verification_stage,
    stage_forbid_needs_human_display,
)


def _load_stdin_json() -> dict[str, Any]:
    """Internal helper for load stdin json."""
    try:
        if sys.stdin.isatty():
            return {}
    except Exception:
        pass
    try:
        raw = sys.stdin.read().strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _print_json(value: dict[str, Any], exit_code: int = 0) -> None:
    """Internal helper for print json."""
    sys.stdout.write(json.dumps(value, indent=2) + "\n")
    raise SystemExit(exit_code)


def _print_text(value: str, exit_code: int = 0) -> None:
    """Internal helper for print text."""
    sys.stdout.write(value.rstrip() + "\n")
    raise SystemExit(exit_code)


def _cli_json(args: list[str], cwd: Path) -> tuple[int, dict[str, Any]]:
    # Bridge hooks call the CLI in-process so all policy decisions stay in one
    # place and hooks only translate payloads to/from JSON.
    """Internal helper for cli json."""
    stdout_buffer = StringIO()
    exit_code = 0
    with redirect_stdout(stdout_buffer):
        try:
            run_command(args, cwd)
        except SystemExit as exc:
            exit_code = int(exc.code) if isinstance(exc.code, int) else 1
    stdout = stdout_buffer.getvalue().strip() or "{}"
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {"raw": stdout}
    return exit_code, payload


def _truncate_for_log(value: Any, *, max_string: int = 500, max_items: int = 20, depth: int = 0) -> Any:
    """Return a compact JSON-safe payload preview for hook diagnostics."""
    if depth >= 4:
        return "<max-depth>"
    if isinstance(value, str):
        return value if len(value) <= max_string else value[: max_string - 20] + "...<truncated>"
    if isinstance(value, dict):
        items = list(value.items())
        preview = {
            str(key): _truncate_for_log(item, max_string=max_string, max_items=max_items, depth=depth + 1)
            for key, item in items[:max_items]
        }
        if len(items) > max_items:
            preview["<truncated_keys>"] = len(items) - max_items
        return preview
    if isinstance(value, list):
        preview = [
            _truncate_for_log(item, max_string=max_string, max_items=max_items, depth=depth + 1)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            preview.append(f"<truncated_items:{len(value) - max_items}>")
        return preview
    return value


def _record_hook_error(
    cwd: Path,
    action: str,
    reason: str,
    *,
    payload: dict[str, Any] | None = None,
    exit_code: int = 2,
    category: str = "hook-rejection",
    traceback_text: str | None = None,
) -> None:
    """Persist hook failures so generic runtime hook errors can be debugged later."""
    ensure_agent_files(cwd)
    event = append_event(
        cwd,
        {
            "type": "hook_error",
            "category": category,
            "action": action,
            "exit_code": exit_code,
            "reason": reason,
            "payload": _truncate_for_log(payload or {}),
            "traceback": traceback_text,
        },
    )
    log_path = artifacts_dir(cwd) / "hook-errors.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def _fail(cwd: Path, action: str, reason: str, payload: dict[str, Any] | None = None) -> None:
    """Internal helper for fail."""
    _record_hook_error(cwd, action, reason, payload=payload)
    sys.stderr.write(reason + "\n")
    raise SystemExit(2)


def _extract_path(payload: dict[str, Any]) -> str | None:
    """Internal helper for extract path."""
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "filePath", "path", "target_path", "targetPath"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def _normalize_target_path_for_policy(cwd: Path, target_path: str) -> str:
    """Internal helper for normalize target path for policy."""
    try:
        path_obj = Path(target_path)
    except OSError:
        return target_path

    if not path_obj.is_absolute():
        return target_path

    try:
        # Convert repo-local absolute paths back to the relative form expected
        # by the path policy matcher.
        return path_obj.resolve().relative_to(cwd.resolve()).as_posix()
    except ValueError:
        return target_path


def _extract_command(payload: dict[str, Any]) -> str | None:
    """Internal helper for extract command."""
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    cmd = tool_input.get("cmd")
    return cmd if isinstance(cmd, str) else None


def _extract_exit_code(payload: dict[str, Any]) -> int:
    """Internal helper for extract exit code."""
    response = payload.get("tool_response", {})
    if not isinstance(response, dict):
        return 0
    return int(response.get("exit_code", response.get("exitCode", response.get("status", 0))) or 0)


def _log_target_for_command(stage: str | None, exit_code: int, root_dir: Path | None = None, workflow_id: str | None = None) -> str | None:
    """Internal helper for log target for command."""
    if stage == canonical_verification_stage(root_dir, workflow_id):
        return ".agent/artifacts/final-verification.log"
    if stage == canonical_expected_failure_stage(root_dir, workflow_id) and exit_code != 0:
        return ".agent/artifacts/red-test.log"
    if exit_code != 0:
        return ".agent/artifacts/command-failure.log"
    return None


def _write_command_log(root_dir: Path, command: str, stdout: str, stderr: str, log_path: str) -> str:
    """Internal helper for write command log."""
    target_dir = artifacts_dir(root_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = root_dir / log_path
    body = "\n\n".join(part for part in [f"command: {command}", stdout, stderr] if part)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(body + "\n", encoding="utf-8")
    return log_path.relative_to(root_dir).as_posix()


def _handle_session_start(cwd: Path, action: str = "session-start") -> None:
    """Internal helper for handle session start."""
    code, payload = _cli_json(["session-start"], cwd)
    if code != 0:
        _fail(cwd, action, str(payload.get("error", "session-start failed")), payload)
    prompt_block = payload.get("prompt_block")
    if isinstance(prompt_block, str) and prompt_block.strip():
        _print_json(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": prompt_block,
                }
            },
            0,
        )
    _print_json(payload, 0)


def _handle_pre_write(cwd: Path, payload: dict[str, Any], action: str = "pre-write") -> None:
    """Internal helper for handle pre write."""
    target_path = _extract_path(payload)
    if not target_path:
        raise SystemExit(0)
    target_path = _normalize_target_path_for_policy(cwd, target_path)
    code, result = _cli_json(["can-write", target_path], cwd)
    if code != 0:
        writable_paths = result.get("writable_paths")
        if isinstance(writable_paths, list) and writable_paths:
            allowed = ", ".join(str(item) for item in writable_paths)
            fallback = f"{result.get('reason') or result.get('error') or 'write blocked'} Allowed write paths: {allowed}"
        else:
            stage = result.get("stage")
            fallback = str(result.get("reason") or result.get("error") or "write blocked")
            if stage and "does not allow agent writes" not in fallback:
                fallback = f"{fallback} Current stage {stage} does not allow agent writes."
        _fail(cwd, action, str(result.get("display_reason") or fallback), payload)


def _handle_pre_command(cwd: Path, payload: dict[str, Any] | None = None, action: str = "pre-command") -> None:
    """Internal helper for handle pre command."""
    code, result = _cli_json(["check-failure-loop"], cwd)
    if code != 0:
        _fail(cwd, action, str(result.get("reason") or result.get("error") or "command blocked"), payload)


def _handle_pre_dispatch(cwd: Path, payload: dict[str, Any]) -> None:
    """Internal helper for handle pre dispatch."""
    if _extract_path(payload):
        _handle_pre_write(cwd, payload, action="pre-dispatch")
        return
    if _extract_command(payload):
        _handle_pre_command(cwd, payload, action="pre-dispatch")


def _handle_post_command(cwd: Path, payload: dict[str, Any], action: str = "post-command") -> None:
    """Internal helper for handle post command."""
    command = _extract_command(payload)
    if not command:
        raise SystemExit(0)
    state = load_state(cwd)
    tool_response = payload.get("tool_response", {})
    stdout = tool_response.get("stdout", tool_response.get("output", "")) if isinstance(tool_response, dict) else ""
    stderr = tool_response.get("stderr", tool_response.get("error", "")) if isinstance(tool_response, dict) else ""
    exit_code = _extract_exit_code(payload)
    workflow_id = str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None
    log_path = _log_target_for_command(state.get("stage"), exit_code, cwd, workflow_id)
    args = ["record-command", "--cmd", command, "--exit-code", str(exit_code)]
    if log_path:
        args.extend(["--log", _write_command_log(cwd, command, str(stdout or ""), str(stderr or ""), log_path)])
    code, result = _cli_json(args, cwd)
    if code != 0:
        _fail(cwd, action, str(result.get("error", "record-command failed")), payload)


def _handle_stop(cwd: Path, action: str = "stop") -> None:
    """Internal helper for handle stop."""
    state = load_state(cwd)
    stage = state.get("stage")
    workflow_id = str(state.get("workflow_id")) if isinstance(state.get("workflow_id"), str) else None
    forbid_display = stage_forbid_needs_human_display(str(stage), cwd, workflow_id) if stage else None
    if forbid_display:
        # Stages with forbid_needs_human must keep progressing through the
        # workflow instead of ending the interaction with a final response.
        _fail(cwd, action, f"agent-guard blocked final response: {forbid_display}", {"state": state})
    if stage and canonical_stage_stop_allowed(str(stage), cwd, workflow_id):
        raise SystemExit(0)
    ready_stage = canonical_completion_ready_stage(cwd, workflow_id)
    if stage != ready_stage and state.get("can_finalize") is not True:
        _fail(
            cwd,
            action,
            "agent-guard blocked final response: "
            f"stage {stage} is still active. Reach the completion-ready stage {ready_stage}, or move to an allowed stop stage first.",
            {"state": state},
        )
    code, payload = _cli_json(["can-finalize"], cwd)
    if code != 0:
        reasons = payload.get("reasons") or [payload.get("reason") or payload.get("error") or "finalization blocked"]
        _fail(cwd, action, "agent-guard blocked finalization: " + "; ".join(str(reason) for reason in reasons), payload)


def _handle_opencode_before(cwd: Path, payload: dict[str, Any]) -> None:
    """Internal helper for handle opencode before."""
    tool = payload.get("tool")
    args = payload.get("args", {})
    tool_payload = {"tool_input": args if isinstance(args, dict) else {}}
    if tool in {"write", "edit", "patch"}:
        _handle_pre_write(cwd, tool_payload, action="opencode-before")
        return
    if tool == "bash":
        _handle_pre_command(cwd, tool_payload, action="opencode-before")


def _handle_opencode_after(cwd: Path, payload: dict[str, Any]) -> None:
    """Internal helper for handle opencode after."""
    input_payload = payload.get("input", {})
    output_payload = payload.get("output", {})
    if not isinstance(input_payload, dict) or input_payload.get("tool") != "bash":
        raise SystemExit(0)
    args = input_payload.get("args", {})
    if not isinstance(args, dict):
        args = {}
    bridge_payload = {
        "tool_input": args,
        "tool_response": output_payload if isinstance(output_payload, dict) else {},
    }
    _handle_post_command(cwd, bridge_payload, action="opencode-after")


def main() -> None:
    """Run the module entry point."""
    action = sys.argv[1] if len(sys.argv) > 1 else None
    cwd = Path.cwd()
    payload = _load_stdin_json()

    try:
        if action == "session-start":
            _handle_session_start(cwd, action="session-start")
        elif action == "pre-write":
            _handle_pre_write(cwd, payload, action="pre-write")
        elif action == "pre-command":
            _handle_pre_command(cwd, payload, action="pre-command")
        elif action == "pre-dispatch":
            _handle_pre_dispatch(cwd, payload)
        elif action == "post-command":
            _handle_post_command(cwd, payload, action="post-command")
        elif action == "stop":
            _handle_stop(cwd, action="stop")
        elif action == "opencode-event":
            event_action = payload.get("action")
            event_payload = payload.get("payload", {})
            if not isinstance(event_payload, dict):
                event_payload = {}
            if event_action == "session-start":
                _handle_session_start(cwd, action="opencode-event:session-start")
            elif event_action == "opencode-before":
                _handle_opencode_before(cwd, event_payload)
            elif event_action == "opencode-after":
                _handle_opencode_after(cwd, event_payload)
            else:
                _print_json({"error": f"Unknown OpenCode event action: {event_action}"}, 1)
        else:
            _print_json({"error": f"Unknown bridge action: {action}"}, 1)
    except SystemExit:
        raise
    except Exception as exc:
        traceback_text = traceback.format_exc()
        _record_hook_error(
            cwd,
            str(action or "<missing-action>"),
            str(exc),
            payload=payload,
            exit_code=2,
            category="hook-exception",
            traceback_text=traceback_text,
        )
        sys.stderr.write(f"agent-guard hook crashed during {action}: {exc}\n")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
