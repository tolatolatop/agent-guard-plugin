import json
from contextlib import redirect_stdout
from io import StringIO

import yaml

from agent_guard.cli import run_command
from agent_guard.state import load_state
from agent_guard.transitions import advance_stage, complete_step, mark_done, ready_to_summarize

from .helpers import make_temp_repo, write_state


def write_plan(root_dir, payload) -> None:
    (root_dir / ".agent" / "plan.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def read_events(root_dir) -> list[dict[str, object]]:
    lines = (root_dir / ".agent" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def invoke_cli(root_dir, argv: list[str]) -> tuple[int, dict[str, object]]:
    stdout = StringIO()
    code = 0
    with redirect_stdout(stdout):
        try:
            run_command(argv, root_dir)
        except SystemExit as exc:
            code = int(exc.code)
    return code, json.loads(stdout.getvalue())


def test_advance_stage_allows_legal_transition_and_blocks_illegal_transition() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="CLARIFYING")

    result = advance_stage(root_dir, "PLANNING")
    assert result["state"]["stage"] == "PLANNING"

    try:
        advance_stage(root_dir, "DONE")
    except RuntimeError as exc:
        assert "Illegal transition" in str(exc)
    else:
        raise AssertionError("Expected illegal transition to fail")


def test_complete_step_updates_progress_and_inherits_scope_from_plan() -> None:
    root_dir = make_temp_repo()
    write_plan(
        root_dir,
        {
            "task_id": "password-reset",
            "steps": [
                {
                    "id": "red-001",
                    "stage": "RED_TEST",
                    "goal": "write red test",
                    "allowed_paths": ["tests/**"],
                    "forbidden_paths": ["src/**"],
                },
                {
                    "id": "green-001",
                    "stage": "GREEN_IMPL",
                    "goal": "make it pass",
                    "allowed_paths": ["src/**", "tests/**"],
                    "forbidden_paths": ["infra/**"],
                },
            ],
        },
    )
    write_state(
        root_dir,
        task_id="password-reset",
        stage="RED_TEST",
        current_step="red-001",
        completed_steps=[],
        remaining_steps=["red-001", "green-001"],
        allowed_paths=["tests/**"],
        forbidden_paths=["src/**"],
    )

    result = complete_step(root_dir, "red-001", "GREEN_IMPL", next_step_id="green-001")

    state = result["state"]
    assert state["completed_steps"] == ["red-001"]
    assert state["remaining_steps"] == ["green-001"]
    assert state["current_step"] == "green-001"
    assert state["allowed_paths"] == ["src/**", "tests/**"]
    assert state["forbidden_paths"] == ["infra/**"]


def test_advance_stage_uses_explicit_scope_when_plan_step_is_missing() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="PLANNING")

    result = advance_stage(
        root_dir,
        "RED_TEST",
        step_id="red-001",
        allowed_paths=["tests/**"],
        forbidden_paths=["src/**"],
    )

    state = result["state"]
    assert state["stage"] == "RED_TEST"
    assert state["current_step"] == "red-001"
    assert state["allowed_paths"] == ["tests/**"]
    assert state["forbidden_paths"] == ["src/**"]


def test_ready_to_summarize_is_blocked_without_successful_verification() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="VERIFY", remaining_steps=[])

    try:
        ready_to_summarize(root_dir)
    except RuntimeError as exc:
        assert "last_verification" in str(exc)
    else:
        raise AssertionError("Expected ready-to-summarize to fail")


def test_mark_done_is_blocked_unless_can_finalize_passes() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="READY_TO_SUMMARIZE", can_finalize=False)

    try:
        mark_done(root_dir)
    except RuntimeError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("Expected mark-done to fail")


def test_needs_failure_analysis_cannot_exit_without_artifact() -> None:
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="password-reset",
        stage="NEEDS_FAILURE_ANALYSIS",
        current_step="green-001",
        remaining_steps=["green-001"],
    )

    try:
        advance_stage(root_dir, "GREEN_IMPL", step_id="green-001", allowed_paths=["src/**"])
    except RuntimeError as exc:
        assert "failure-analysis.md" in str(exc)
    else:
        raise AssertionError("Expected transition to be blocked")


def test_done_cannot_be_advanced_further() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="DONE", can_finalize=True)

    try:
        advance_stage(root_dir, "CLARIFYING")
    except RuntimeError as exc:
        assert "DONE cannot transition" in str(exc)
    else:
        raise AssertionError("Expected DONE transition to fail")


def test_transition_appends_event() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="CLARIFYING")

    advance_stage(root_dir, "PLANNING")

    events = read_events(root_dir)
    assert events[-1]["hook"] == "WorkflowTransition"
    assert events[-1]["from_stage"] == "CLARIFYING"
    assert events[-1]["to_stage"] == "PLANNING"


def test_cli_representative_flow_from_start_to_done() -> None:
    root_dir = make_temp_repo()
    write_plan(
        root_dir,
        {
            "task_id": "password-reset",
            "steps": [
                {
                    "id": "red-001",
                    "stage": "RED_TEST",
                    "goal": "write red test",
                    "allowed_paths": ["tests/**"],
                    "forbidden_paths": ["src/**"],
                },
                {
                    "id": "green-001",
                    "stage": "GREEN_IMPL",
                    "goal": "implement fix",
                    "allowed_paths": ["src/**", "tests/**"],
                    "forbidden_paths": ["infra/**"],
                },
            ],
        },
    )

    assert invoke_cli(root_dir, ["start-task", "password-reset"])[0] == 0
    assert invoke_cli(root_dir, ["advance-stage", "--to", "PLANNING"])[0] == 0
    assert invoke_cli(root_dir, ["advance-stage", "--to", "RED_TEST", "--step", "red-001"])[0] == 0
    assert invoke_cli(
        root_dir,
        ["complete-step", "red-001", "--next-stage", "GREEN_IMPL", "--next-step", "green-001"],
    )[0] == 0

    code, _ = invoke_cli(root_dir, ["advance-stage", "--to", "REVIEW"])
    assert code == 1

    code, _ = invoke_cli(root_dir, ["complete-step", "green-001", "--next-stage", "REVIEW"])
    assert code == 0
    (root_dir / ".agent" / "artifacts" / "review.json").write_text("{}\n", encoding="utf-8")
    assert invoke_cli(root_dir, ["advance-stage", "--to", "VERIFY"])[0] == 0

    write_state(
        root_dir,
        **{
            **load_state(root_dir),
            "stage": "VERIFY",
            "current_step": None,
            "remaining_steps": [],
            "last_verification": {
                "command": "pytest",
                "exit_code": 0,
                "log_path": ".agent/artifacts/final-verification.log",
                "recorded_at": "2026-05-12T10:00:00Z",
            },
        },
    )
    assert invoke_cli(root_dir, ["ready-to-summarize"])[0] == 0
    assert invoke_cli(root_dir, ["mark-done"])[0] == 0
    assert load_state(root_dir)["stage"] == "DONE"


def test_cli_failed_verify_requires_failure_analysis_then_allows_reentry() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="VERIFY", current_step="verify-001")
    log_path = ".agent/artifacts/final-verification.log"
    (root_dir / log_path).write_text("boom\n", encoding="utf-8")

    code, _ = invoke_cli(root_dir, ["record-command", "--cmd", "pytest", "--exit-code", "1", "--log", log_path])
    assert code == 0
    assert load_state(root_dir)["stage"] == "NEEDS_FAILURE_ANALYSIS"

    code, payload = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001", "--allowed-paths", "src/**"],
    )
    assert code == 1
    assert "failure-analysis.md" in payload["error"]

    (root_dir / ".agent" / "artifacts" / "failure-analysis.md").write_text("## Failure Summary\n", encoding="utf-8")
    code, _ = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001", "--allowed-paths", "src/**"],
    )
    assert code == 0
