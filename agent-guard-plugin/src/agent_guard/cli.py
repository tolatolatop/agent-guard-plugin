"""Command-line entry points for agent-guard."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .failures import check_failure_loop, record_command_result
from .gates import can_finalize
from .install import install_runtime, parse_flags, uninstall_runtime
from .jobs import check_job_poll, load_jobs
from .plan import load_plan_summary
from .path_policy import decide_write
from .runtime_adapter import get_next_step, get_session_reminder
from .state import AGENT_DIR, ensure_agent_files, load_state, update_state
from .task_reset import reset_task
from .transitions import (
    advance_stage,
    complete_step,
    mark_done,
    parse_scope_flag,
    ready_to_summarize,
)
from .wizard import run_wizard


GLOBAL_HELP = """Usage: agent-guard <command> [options]

Minimal runtime guard CLI for coding-agent workflows.

Commands:
  init                              Initialize .agent state files in the current repo.
  start-task <task-id>              Start or register a task.
  reset-task <task-id>              Archive completed task state and initialize a new task.
  next-task <task-id>               Alias for reset-task.
  status                            Show current state, jobs, plan summary, and next step.
  session-start                     Emit a concise session reminder.
  can-write <path>                  Check whether a file write is allowed in the current stage.
  record-command --cmd CMD --exit-code CODE [--log PATH]
                                    Record command execution details.
  advance-stage --to STAGE [--step STEP_ID] [--allowed-paths CSV] [--forbidden-paths CSV]
                                    Move the workflow to a new stage.
  complete-step <step-id> --next-stage STAGE [--next-step STEP_ID]
                [--allowed-paths CSV] [--forbidden-paths CSV]
                                    Mark the current step complete and advance workflow state.
  ready-to-summarize                Mark the workflow as ready for final summarization.
  mark-done                         Mark the workflow as done.
  check-failure-loop                Check whether repeated failures should block progress.
  check-job-poll <job-id>           Check whether a job may be polled now.
  can-finalize                      Check whether finalization is allowed.
  next-step                         Show the next step derived from state and plan.
  install [options]                 Install runtime integrations for supported tools.
  uninstall [options]               Remove runtime integrations for supported tools.
  wizard                            Run the interactive setup wizard.
  help [command]                    Show general or command-specific help.

Global options:
  -h, --help                        Show help.

Examples:
  agent-guard init
  agent-guard start-task password-reset
  agent-guard can-write tests/test_auth.py
  agent-guard record-command --cmd "pytest tests/test_auth.py" --exit-code 1 --log .agent/artifacts/red-test.log
  agent-guard install --runtime codex --scope project
"""

COMMAND_HELP: dict[str, str] = {
    "init": "Usage: agent-guard init\n\nInitialize .agent state files in the current repository.",
    "start-task": "Usage: agent-guard start-task <task-id>\n\nStart or register a task and move IDLE repositories into CLARIFYING.",
    "reset-task": "Usage: agent-guard reset-task <task-id>\n\nArchive completed task state and initialize a new task.",
    "next-task": "Usage: agent-guard next-task <task-id>\n\nAlias for reset-task.",
    "status": "Usage: agent-guard status\n\nShow current state, jobs, plan summary, and next step.",
    "session-start": "Usage: agent-guard session-start\n\nEmit a concise session reminder for hooks and agents.",
    "can-write": "Usage: agent-guard can-write <path>\n\nCheck whether a file write is allowed in the current stage.",
    "record-command": (
        "Usage: agent-guard record-command --cmd CMD --exit-code CODE [--log PATH]\n\n"
        "Record command execution details, exit code, and optional log path."
    ),
    "advance-stage": (
        "Usage: agent-guard advance-stage --to STAGE [--step STEP_ID] [--allowed-paths CSV] [--forbidden-paths CSV]\n\n"
        "Move the workflow to a new stage."
    ),
    "complete-step": (
        "Usage: agent-guard complete-step <step-id> --next-stage STAGE [--next-step STEP_ID] "
        "[--allowed-paths CSV] [--forbidden-paths CSV]\n\n"
        "Mark the current step complete and advance workflow state."
    ),
    "ready-to-summarize": "Usage: agent-guard ready-to-summarize\n\nMark the workflow as ready for final summarization.",
    "mark-done": "Usage: agent-guard mark-done\n\nMark the workflow as done.",
    "check-failure-loop": "Usage: agent-guard check-failure-loop\n\nCheck whether repeated failures should block progress.",
    "check-job-poll": "Usage: agent-guard check-job-poll <job-id>\n\nCheck whether a job may be polled now.",
    "can-finalize": "Usage: agent-guard can-finalize\n\nCheck whether finalization is allowed.",
    "next-step": "Usage: agent-guard next-step\n\nShow the next step derived from state and plan.",
    "install": (
        "Usage: agent-guard install [--runtime RUNTIME] [--scope SCOPE]\n\n"
        "Install runtime integrations.\n\n"
        "Options:\n"
        "  -r, --runtime RUNTIME   Supported: claude-code, codex, opencode\n"
        "  -s, --scope SCOPE       Supported: project, user"
    ),
    "uninstall": (
        "Usage: agent-guard uninstall [--runtime RUNTIME] [--scope SCOPE]\n\n"
        "Remove runtime integrations.\n\n"
        "Options:\n"
        "  -r, --runtime RUNTIME   Supported: claude-code, codex, opencode\n"
        "  -s, --scope SCOPE       Supported: project, user"
    ),
    "wizard": "Usage: agent-guard wizard\n\nRun the interactive setup wizard.",
    "help": "Usage: agent-guard help [command]\n\nShow general or command-specific help.",
}


def print_json(data: dict[str, Any], exit_code: int = 0) -> None:
    """Print json."""
    sys.stdout.write(json.dumps(data, indent=2) + "\n")
    raise SystemExit(exit_code)


def print_help(text: str, exit_code: int = 0) -> None:
    """Print plain-text help."""
    sys.stdout.write(text.rstrip() + "\n")
    raise SystemExit(exit_code)


def command_help(command: str) -> str:
    """Return help text for a command."""
    return COMMAND_HELP.get(command, f"Unknown command: {command}\n\n{GLOBAL_HELP}")


def ensure_path_arg(rest: list[str], name: str) -> str:
    """Ensure path arg."""
    if not rest:
        print_json({"error": f"Missing required argument: {name}"}, 1)
    return rest[0]


def run_command(argv: list[str], cwd: Path) -> int:
    """Run command."""
    if not argv:
        print_help(GLOBAL_HELP, 1)

    if argv[0] in {"-h", "--help"}:
        print_help(GLOBAL_HELP)

    if argv[0] == "help":
        target = argv[1] if len(argv) > 1 else None
        print_help(command_help(target) if target else GLOBAL_HELP)

    command, *rest = argv

    if any(flag in {"-h", "--help"} for flag in rest):
        print_help(command_help(command))

    try:
        if command == "init":
            ensure_agent_files(cwd)
            print_json({"ok": True, "agent_dir": str(cwd / AGENT_DIR)})
        elif command == "start-task":
            task_id = ensure_path_arg(rest, "task-id")
            ensure_agent_files(cwd)
            state = update_state(
                cwd,
                lambda current: {
                    **current,
                    "task_id": task_id,
                    "stage": "CLARIFYING" if current["stage"] == "IDLE" else current["stage"],
                },
            )
            print_json({"ok": True, "state": state})
        elif command in {"reset-task", "next-task"}:
            task_id = ensure_path_arg(rest, "task-id")
            result = reset_task(cwd, task_id)
            print_json({"ok": True, **result})
        elif command == "status":
            state = load_state(cwd)
            print_json(
                {
                    "ok": True,
                    "state": state,
                    "jobs": load_jobs(cwd),
                    "plan": load_plan_summary(cwd),
                    "next_step": get_next_step(cwd, state),
                }
            )
        elif command == "session-start":
            print_json({"ok": True, **get_session_reminder(cwd)})
        elif command == "can-write":
            decision = decide_write(load_state(cwd), ensure_path_arg(rest, "path"))
            print_json(decision, 0 if decision["decision"] == "allow" else 1)
        elif command == "record-command":
            flags = parse_flags(rest)
            if "cmd" not in flags or "exit-code" not in flags:
                print_json(
                    {
                        "error": (
                            'Usage: agent-guard record-command --cmd "<command>" '
                            "--exit-code <code> [--log <path>]"
                        )
                    },
                    1,
                )
            result = record_command_result(
                cwd,
                str(flags["cmd"]),
                int(str(flags["exit-code"])),
                str(flags["log"]) if "log" in flags else None,
            )
            print_json({"ok": True, **result})
        elif command == "advance-stage":
            flags = parse_flags(rest)
            if "to" not in flags:
                print_json(
                    {
                        "error": (
                            "Usage: agent-guard advance-stage --to <stage> [--step <step-id>] "
                            "[--allowed-paths <csv>] [--forbidden-paths <csv>]"
                        )
                    },
                    1,
                )
            result = advance_stage(
                cwd,
                str(flags["to"]),
                step_id=str(flags["step"]) if "step" in flags else None,
                allowed_paths=parse_scope_flag(flags.get("allowed-paths")),
                forbidden_paths=parse_scope_flag(flags.get("forbidden-paths")),
            )
            print_json({"ok": True, **result})
        elif command == "complete-step":
            step_id = ensure_path_arg(rest, "step-id")
            flags = parse_flags(rest[1:])
            if "next-stage" not in flags:
                print_json(
                    {
                        "error": (
                            "Usage: agent-guard complete-step <step-id> --next-stage <stage> "
                            "[--next-step <step-id>] [--allowed-paths <csv>] [--forbidden-paths <csv>]"
                        )
                    },
                    1,
                )
            result = complete_step(
                cwd,
                step_id,
                str(flags["next-stage"]),
                next_step_id=str(flags["next-step"]) if "next-step" in flags else None,
                allowed_paths=parse_scope_flag(flags.get("allowed-paths")),
                forbidden_paths=parse_scope_flag(flags.get("forbidden-paths")),
            )
            print_json({"ok": True, **result})
        elif command == "ready-to-summarize":
            print_json({"ok": True, **ready_to_summarize(cwd)})
        elif command == "mark-done":
            print_json({"ok": True, **mark_done(cwd)})
        elif command == "check-failure-loop":
            result = check_failure_loop(cwd)
            print_json(result, 0 if result["decision"] == "allow" else 1)
        elif command == "check-job-poll":
            result = check_job_poll(cwd, ensure_path_arg(rest, "job-id"))
            print_json(result, 0 if result["decision"] == "allow" else 1)
        elif command == "can-finalize":
            result = can_finalize(cwd)
            print_json(result, 0 if result["decision"] == "allow" else 1)
        elif command == "next-step":
            print_json({"ok": True, "next_step": get_next_step(cwd, load_state(cwd))})
        elif command == "install":
            result = install_runtime(rest, cwd, Path(os.path.expanduser("~")), Path(__file__).resolve().parents[2])
            print_json({"ok": True, **result})
        elif command == "uninstall":
            result = uninstall_runtime(
                rest,
                cwd,
                Path(os.path.expanduser("~")),
                output=sys.stdout,
                input_stream=sys.stdin,
            )
            print_json({"ok": True, **result})
        elif command == "wizard":
            result = run_wizard(cwd, sys.stdin, sys.stdout)
            print_json(result)
        else:
            print_json(
                {
                    "error": (
                        "Unknown command. Supported: init, start-task, status, session-start, "
                        "can-write, record-command, advance-stage, complete-step, ready-to-summarize, "
                        "mark-done, check-failure-loop, check-job-poll, can-finalize, next-step, "
                        "reset-task, next-task, install, uninstall, wizard"
                    )
                },
                1,
            )
    except RuntimeError as exc:
        print_json({"error": str(exc)}, 1)
    return 0


def main() -> None:
    """Run the module entry point."""
    run_command(sys.argv[1:], Path.cwd())


def install_main() -> None:
    """Run the install entry point."""
    try:
        result = install_runtime(sys.argv[1:], Path.cwd(), Path(os.path.expanduser("~")), Path(__file__).resolve().parents[2])
        print_json({"ok": True, **result})
    except RuntimeError as exc:
        print_json({"error": str(exc)}, 1)


def uninstall_main() -> None:
    """Run the uninstall entry point."""
    try:
        result = uninstall_runtime(
            sys.argv[1:],
            Path.cwd(),
            Path(os.path.expanduser("~")),
            output=sys.stdout,
            input_stream=sys.stdin,
        )
        print_json({"ok": True, **result})
    except RuntimeError as exc:
        print_json({"error": str(exc)}, 1)


if __name__ == "__main__":
    main()
