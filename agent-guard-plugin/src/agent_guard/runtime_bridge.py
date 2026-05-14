from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from .cli import run_command
from .state import artifacts_dir, load_state
from .workflow_spec import stage_forbid_needs_human_display


def _load_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _print_json(value: dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(value, indent=2) + "\n")
    raise SystemExit(exit_code)


def _print_text(value: str, exit_code: int = 0) -> None:
    sys.stdout.write(value.rstrip() + "\n")
    raise SystemExit(exit_code)


def _cli_json(args: list[str], cwd: Path) -> tuple[int, dict[str, Any]]:
    # Bridge hooks call the CLI in-process so all policy decisions stay in one
    # place and hooks only translate payloads to/from JSON.
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


def _fail(reason: str) -> None:
    sys.stderr.write(reason + "\n")
    raise SystemExit(2)


def _extract_path(payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "filePath", "path", "target_path", "targetPath"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def _normalize_target_path_for_policy(cwd: Path, target_path: str) -> str:
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
    response = payload.get("tool_response", {})
    if not isinstance(response, dict):
        return 0
    return int(response.get("exit_code", response.get("exitCode", response.get("status", 0))) or 0)


def _log_target_for_command(stage: str | None, exit_code: int) -> str | None:
    if stage == "VERIFY":
        return ".agent/artifacts/final-verification.log"
    if stage == "RED_TEST" and exit_code != 0:
        return ".agent/artifacts/red-test.log"
    if exit_code != 0:
        return ".agent/artifacts/command-failure.log"
    return None


def _write_command_log(root_dir: Path, command: str, stdout: str, stderr: str, log_path: str) -> str:
    target_dir = artifacts_dir(root_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = root_dir / log_path
    body = "\n\n".join(part for part in [f"command: {command}", stdout, stderr] if part)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(body + "\n", encoding="utf-8")
    return log_path.relative_to(root_dir).as_posix()


def _handle_session_start(cwd: Path) -> None:
    code, payload = _cli_json(["session-start"], cwd)
    if code != 0:
        _fail(str(payload.get("error", "session-start failed")))
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


def _handle_pre_write(cwd: Path, payload: dict[str, Any]) -> None:
    target_path = _extract_path(payload)
    if not target_path:
        raise SystemExit(0)
    target_path = _normalize_target_path_for_policy(cwd, target_path)
    code, result = _cli_json(["can-write", target_path], cwd)
    if code != 0:
        _fail(str(result.get("reason") or result.get("error") or "write blocked"))


def _handle_pre_command(cwd: Path) -> None:
    code, result = _cli_json(["check-failure-loop"], cwd)
    if code != 0:
        _fail(str(result.get("reason") or result.get("error") or "command blocked"))


def _handle_pre_dispatch(cwd: Path, payload: dict[str, Any]) -> None:
    if _extract_path(payload):
        _handle_pre_write(cwd, payload)
        return
    if _extract_command(payload):
        _handle_pre_command(cwd)


def _handle_post_command(cwd: Path, payload: dict[str, Any]) -> None:
    command = _extract_command(payload)
    if not command:
        raise SystemExit(0)
    state = load_state(cwd)
    tool_response = payload.get("tool_response", {})
    stdout = tool_response.get("stdout", tool_response.get("output", "")) if isinstance(tool_response, dict) else ""
    stderr = tool_response.get("stderr", tool_response.get("error", "")) if isinstance(tool_response, dict) else ""
    exit_code = _extract_exit_code(payload)
    log_path = _log_target_for_command(state.get("stage"), exit_code)
    args = ["record-command", "--cmd", command, "--exit-code", str(exit_code)]
    if log_path:
        args.extend(["--log", _write_command_log(cwd, command, str(stdout or ""), str(stderr or ""), log_path)])
    code, result = _cli_json(args, cwd)
    if code != 0:
        _fail(str(result.get("error", "record-command failed")))


def _handle_stop(cwd: Path) -> None:
    state = load_state(cwd)
    stage = state.get("stage")
    forbid_display = stage_forbid_needs_human_display(str(stage)) if stage else None
    if forbid_display:
        # Stages with forbid_needs_human must keep progressing through the
        # workflow instead of ending the interaction with a final response.
        _fail(f"agent-guard blocked final response: {forbid_display}")
    if stage in {"IDLE", "CLARIFYING", "DESIGNING", "PLANNING", "NEEDS_HUMAN", "DONE"}:
        raise SystemExit(0)
    if stage != "READY_TO_SUMMARIZE" and state.get("can_finalize") is not True:
        _fail(
            "agent-guard blocked final response: "
            f"stage {stage} is still active. Reach REVIEW completion and READY_TO_SUMMARIZE, or move to an allowed stop stage first."
        )
    code, payload = _cli_json(["can-finalize"], cwd)
    if code != 0:
        reasons = payload.get("reasons") or [payload.get("reason") or payload.get("error") or "finalization blocked"]
        _fail("agent-guard blocked finalization: " + "; ".join(str(reason) for reason in reasons))


def _handle_opencode_before(cwd: Path, payload: dict[str, Any]) -> None:
    tool = payload.get("tool")
    args = payload.get("args", {})
    tool_payload = {"tool_input": args if isinstance(args, dict) else {}}
    if tool in {"write", "edit", "patch"}:
        _handle_pre_write(cwd, tool_payload)
        return
    if tool == "bash":
        _handle_pre_command(cwd)


def _handle_opencode_after(cwd: Path, payload: dict[str, Any]) -> None:
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
    _handle_post_command(cwd, bridge_payload)


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else None
    cwd = Path.cwd()
    payload = _load_stdin_json()

    if action == "session-start":
        _handle_session_start(cwd)
    elif action == "pre-write":
        _handle_pre_write(cwd, payload)
    elif action == "pre-command":
        _handle_pre_command(cwd)
    elif action == "pre-dispatch":
        _handle_pre_dispatch(cwd, payload)
    elif action == "post-command":
        _handle_post_command(cwd, payload)
    elif action == "stop":
        _handle_stop(cwd)
    elif action == "opencode-event":
        event_action = payload.get("action")
        event_payload = payload.get("payload", {})
        if not isinstance(event_payload, dict):
            event_payload = {}
        if event_action == "session-start":
            _handle_session_start(cwd)
        elif event_action == "opencode-before":
            _handle_opencode_before(cwd, event_payload)
        elif event_action == "opencode-after":
            _handle_opencode_after(cwd, event_payload)
        else:
            _print_json({"error": f"Unknown OpenCode event action: {event_action}"}, 1)
    else:
        _print_json({"error": f"Unknown bridge action: {action}"}, 1)


if __name__ == "__main__":
    main()
