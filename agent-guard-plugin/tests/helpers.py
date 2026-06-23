"""Tests for helpers."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

from agent_guard.state import DEFAULT_STATE, ensure_agent_files, save_state


def make_temp_repo() -> Path:
    """Helper for make temp repo."""
    root_dir = Path(tempfile.mkdtemp(prefix="agent-guard-"))
    ensure_agent_files(root_dir)
    return root_dir


def write_state(root_dir: Path, **override: object) -> dict[str, object]:
    """Helper for write state."""
    state = {**DEFAULT_STATE, **override}
    state.pop("allowed_paths", None)
    state.pop("forbidden_paths", None)
    save_state(root_dir, state)
    return state


def runtime_test_env() -> dict[str, str]:
    """Return an environment that can import the local src package."""
    repo_root = Path(__file__).resolve().parents[1]
    existing = os.environ.get("PYTHONPATH")
    src_path = str(repo_root / "src")
    pythonpath = src_path if not existing else f"{src_path}:{existing}"
    return {**os.environ, "PYTHONPATH": pythonpath}


def standard_workflow_spec_dict() -> dict[str, object]:
    """A minimal but representative workflow spec matching the real default.workflow.yaml.

    Tests that call convenience wrappers (path_policy(), stage_exit_conditions(), etc.)
    without arguments import this spec instead of relying on the packaged default.workflow.yaml.
    """
    return {
        "version": 2,
        "workflow": {
            "id": "standard-ddd-example",
            "title": "Standard Workflow Example",
            "description": "Reference workflow for agent-guard tests.",
            "entry": "CLARIFYING",
        },
        "global_gates": [
            "Do not write outside stage permissions.",
            "Do not retry identical failing commands without code changes or failure analysis.",
            "Do not claim completion unless can-finalize passes.",
            "Do not modify .agent/state.json directly.",
        ],
        "globals": {
            "protected": [".agent/state.json"],
            "sensitive": [
                ".github/**",
                "infra/**",
                "migrations/**",
                "package-lock.json",
                "pnpm-lock.yaml",
                "yarn.lock",
                "poetry.lock",
                "Cargo.lock",
            ],
            "failures": {"repeat_threshold": 2, "fingerprint_roots": ["src", "tests"]},
            "finalize": {
                "require": [
                    {"rule": "no_running_jobs"},
                    {"rule": "successful_last_verification"},
                    {"rule": "can_finalize_flag"},
                    {"rule": "all_plan_steps_terminal"},
                ],
                "messages": {
                    "no_running_jobs": "running jobs still exist",
                    "successful_last_verification": "last_verification.exit_code must be 0",
                    "can_finalize_flag": "state.can_finalize is not true",
                    "all_plan_steps_terminal": "all plan steps must be done or failed",
                },
            },
            "wizard": {"start_stages": ["CLARIFYING", "PLANNING", "RED_TEST", "GREEN_IMPL"]},
            "session_start": {"navigator_skill": "using-workflow"},
            "install": {"skills": {"match": [], "exclude_match": []}},
        },
        "stages": {
            "IDLE": {
                "goal": "Load task state and determine the next concrete step.",
                "plan": "deny",
                "allow": {"write": [".agent/**"], "actions": [], "stop": True, "human": True},
                "deny": {"write": [], "actions": []},
                "enter": [
                    {"rule": "active_task", "display": "task_id must be set"}
                ],
                "exit": [],
                "expect": [],
                "next": ["CLARIFYING"],
            },
            "CLARIFYING": {
                "goal": "Resolve task intent, assumptions, and missing inputs before implementation.",
                "plan": "deny",
                "allow": {
                    "write": [".agent/**"],
                    "actions": [],
                    "stop": True,
                    "human": True,
                },
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [],
                "expect": [],
                "next": ["DESIGNING", "PLANNING"],
            },
            "DESIGNING": {
                "goal": "Write the smallest design needed to guide implementation safely.",
                "plan": "deny",
                "allow": {
                    "write": [".agent/artifacts/DESIGN.md"],
                    "actions": [],
                    "stop": False,
                    "human": False,
                },
                "deny": {"write": [], "actions": []},
                "enter": [{"rule": "active_task", "display": "active task exists"}],
                "exit": [".agent/artifacts/DESIGN.md"],
                "expect": [],
                "next": ["PLANNING"],
            },
            "PLANNING": {
                "goal": "Break work into explicit steps with clear success conditions and required evidence.",
                "plan": "create",
                "allow": {"write": [], "actions": [], "stop": True, "human": True},
                "deny": {"write": [], "actions": []},
                "enter": [{"rule": "active_task", "display": "active task exists"}],
                "exit": [],
                "expect": [],
                "next": ["RED_TEST", "GREEN_IMPL"],
            },
            "RED_TEST": {
                "goal": "Create a failing test that proves the missing behavior.",
                "plan": "advance",
                "allow": {"write": ["tests/**"], "actions": [], "stop": False, "human": False},
                "deny": {"write": ["src/**"], "actions": []},
                "enter": [],
                "exit": [
                    {
                        "rule": "command_ran",
                        "value": r"(^|\s)pytest(\s|$)",
                        "display": "must run pytest during RED_TEST",
                    }
                ],
                "expect": [".agent/artifacts/red-test.log"],
                "next": ["GREEN_IMPL", "NEEDS_FAILURE_ANALYSIS"],
            },
            "GREEN_IMPL": {
                "goal": "Implement the smallest code change that makes the targeted test pass.",
                "plan": "advance",
                "allow": {"write": ["**"], "actions": [], "stop": False, "human": False},
                "deny": {"write": [".agent/**"], "actions": []},
                "enter": [],
                "exit": [],
                "expect": [],
                "next": ["REVIEW", "NEEDS_FAILURE_ANALYSIS"],
            },
            "REVIEW": {
                "goal": "Review the diff and capture review evidence without changing code.",
                "plan": "advance",
                "allow": {
                    "write": [".agent/artifacts/review.md"],
                    "actions": [],
                    "stop": False,
                    "human": False,
                },
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [".agent/artifacts/review.md"],
                "expect": [],
                "next": ["VERIFY", "GREEN_IMPL"],
            },
            "VERIFY": {
                "goal": "Run verification commands and record final evidence.",
                "plan": "advance",
                "allow": {
                    "write": [".agent/artifacts/final-verification.log"],
                    "actions": [],
                    "stop": False,
                    "human": False,
                },
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [
                    ".agent/artifacts/final-verification.log",
                    {
                        "rule": "command_ran",
                        "value": r"(^|\s)pytest(\s|$)",
                        "display": "must run pytest during VERIFY",
                    },
                    {
                        "rule": "command_succeeded",
                        "value": r"(^|\s)pytest(\s|$)",
                        "display": "pytest must succeed during VERIFY",
                    },
                ],
                "expect": [],
                "next": [
                    "READY_TO_SUMMARIZE",
                    "RED_TEST",
                    "GREEN_IMPL",
                    "NEEDS_FAILURE_ANALYSIS",
                ],
            },
            "READY_TO_SUMMARIZE": {
                "goal": "Summarize completed work and verification results without further edits.",
                "plan": "complete",
                "allow": {
                    "write": [".agent/artifacts/summary.md"],
                    "actions": [],
                    "stop": False,
                    "human": False,
                },
                "deny": {"write": [], "actions": []},
                "enter": [
                    {
                        "rule": "required_command",
                        "value": "ready-to-summarize",
                        "display": "use ready-to-summarize",
                    },
                    {"rule": "no_running_jobs", "display": "no running jobs"},
                    {
                        "rule": "all_plan_steps_terminal",
                        "display": "all plan steps must be done or failed",
                    },
                    {"display": "can_finalize enabled only through ready-to-summarize"},
                ],
                "exit": [".agent/artifacts/summary.md"],
                "expect": [],
                "next": ["DONE"],
            },
            "NEEDS_FAILURE_ANALYSIS": {
                "goal": "Stop retry loops and produce evidence-backed failure analysis before changing code again.",
                "plan": "follow",
                "allow": {
                    "write": [".agent/artifacts/**"],
                    "actions": [],
                    "stop": False,
                    "human": False,
                },
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [
                    {
                        "path": ".agent/artifacts/failure-analysis.md",
                        "matches": r"^## Failure Summary",
                        "display": "failure-analysis.md must start with the Failure Summary section.",
                    }
                ],
                "expect": [],
                "next": ["RED_TEST", "GREEN_IMPL", "VERIFY", "NEEDS_HUMAN"],
            },
            "NEEDS_HUMAN": {
                "goal": "Escalate blocked or risky work for human review.",
                "plan": "deny",
                "allow": {
                    "write": [".agent/**"],
                    "actions": [],
                    "stop": True,
                    "human": True,
                },
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [],
                "expect": [],
                "next": ["CLARIFYING", "PLANNING"],
            },
            "DONE": {
                "goal": "Task is complete; preserve state and await the next task.",
                "plan": "complete",
                "final": True,
                "allow": {"write": [".agent/**"], "actions": [], "stop": True, "human": True},
                "deny": {"write": [], "actions": []},
                "enter": [
                    {
                        "rule": "required_command",
                        "value": "mark-done",
                        "display": "use mark-done",
                    },
                    {
                        "rule": "can_finalize_passes",
                        "display": "can-finalize must pass",
                    },
                ],
                "exit": [],
                "expect": [],
                "next": [],
            },
        },
    }


def setup_default_workflow(monkeypatch: Any, tmp_path: Path) -> Path:
    """Write a standard default.workflow.yaml to a temp dir and make load_workflow_spec find it.

    Call at the start of any test that calls convenience wrappers (path_policy(),
    stage_exit_conditions(), etc.) without arguments so the test does not depend on
    the packaged default.workflow.yaml file.

    Usage:
        def test_foo(monkeypatch, tmp_path):
            setup_default_workflow(monkeypatch, tmp_path)
            # now path_policy(), stage_exit_conditions(), etc. work from the temp copy
    """
    import yaml  # noqa: PLC0415

    from agent_guard.workflow_spec import load_workflow_spec  # noqa: PLC0415

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    spec = standard_workflow_spec_dict()
    (user_dir / "default.workflow.yaml").write_text(
        yaml.safe_dump(spec, default_flow_style=False), encoding="utf-8"
    )
    monkeypatch.setattr("agent_guard.workflow_spec.user_workflow_dirs", lambda: [user_dir])
    load_workflow_spec.cache_clear()
    return user_dir
