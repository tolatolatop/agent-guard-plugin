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
from .wizard import run_wizard


def print_json(data: dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(data, indent=2) + "\n")
    raise SystemExit(exit_code)


def ensure_path_arg(rest: list[str], name: str) -> str:
    if not rest:
        print_json({"error": f"Missing required argument: {name}"}, 1)
    return rest[0]


def run_command(argv: list[str], cwd: Path) -> int:
    if not argv:
        print_json({"error": "Missing command"}, 1)

    command, *rest = argv

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
                    "next_step": get_next_step(state),
                }
            )
        elif command == "session-start":
            print_json({"ok": True, **get_session_reminder(cwd)})
        elif command == "can-write":
            decision = decide_write(load_state(cwd), ensure_path_arg(rest, "path"))
            print_json(decision, 0 if decision["decision"] == "allow" else 1)
        elif command == "record-command":
            flags = parse_flags(rest)
            if "cmd" not in flags or "exit-code" not in flags or "log" not in flags:
                print_json(
                    {
                        "error": (
                            'Usage: agent-guard record-command --cmd "<command>" '
                            "--exit-code <code> --log <path>"
                        )
                    },
                    1,
                )
            result = record_command_result(
                cwd,
                str(flags["cmd"]),
                int(str(flags["exit-code"])),
                str(flags["log"]),
            )
            print_json({"ok": True, **result})
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
            print_json({"ok": True, "next_step": get_next_step(load_state(cwd))})
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
                        "can-write, record-command, check-failure-loop, check-job-poll, "
                        "can-finalize, next-step, reset-task, next-task, install, uninstall, wizard"
                    )
                },
                1,
            )
    except RuntimeError as exc:
        print_json({"error": str(exc)}, 1)
    return 0


def main() -> None:
    run_command(sys.argv[1:], Path.cwd())


def install_main() -> None:
    try:
        result = install_runtime(sys.argv[1:], Path.cwd(), Path(os.path.expanduser("~")), Path(__file__).resolve().parents[2])
        print_json({"ok": True, **result})
    except RuntimeError as exc:
        print_json({"error": str(exc)}, 1)


def uninstall_main() -> None:
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
