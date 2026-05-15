"""Tests for test transitions."""
import json
import os
from contextlib import redirect_stdout
from io import StringIO

from agent_guard.cli import run_command
from agent_guard.plan import plan_steps
from agent_guard.state import load_state
from agent_guard.transitions import advance_stage, complete_step, mark_done, ready_to_summarize

from .helpers import make_temp_repo, write_state


def read_events(root_dir) -> list[dict[str, object]]:
    """Helper for read events."""
    lines = (root_dir / ".agent" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def invoke_cli(root_dir, argv: list[str]) -> tuple[int, dict[str, object]]:
    """Helper for invoke cli."""
    stdout = StringIO()
    code = 0
    with redirect_stdout(stdout):
        try:
            run_command(argv, root_dir)
        except SystemExit as exc:
            code = int(exc.code)
    return code, json.loads(stdout.getvalue())


def test_advance_stage_allows_legal_transition_and_blocks_illegal_transition() -> None:
    """Test that advance stage allows legal transition and blocks illegal transition."""
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


def test_complete_step_clears_legacy_dynamic_scope_for_next_execution_step() -> None:
    """Test that complete step clears legacy dynamic scope for next execution step."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: write red test\n"
        "    status: in_progress\n"
        "  - name: green-001\n"
        "    description: make it pass\n"
        "    status: pending\n",
        encoding="utf-8",
    )
    write_state(
        root_dir,
        task_id="password-reset",
        stage="RED_TEST",
        current_step="red-001",
        completed_steps=[],
        remaining_steps=["red-001", "green-001"],
    )

    result = complete_step(
        root_dir,
        "red-001",
        next_step_id="green-001",
    )

    state = result["state"]
    assert state["completed_steps"] == []
    assert state["remaining_steps"] == []
    assert state["current_step"] == "green-001"
    assert state["stage"] == "RED_TEST"
    assert plan_steps(root_dir)[0]["status"] == "done"


def test_advance_stage_drops_legacy_dynamic_scope_when_plan_step_is_missing() -> None:
    """Test that advance stage drops legacy dynamic scope when plan step is missing."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="PLANNING")
    (root_dir / ".agent" / "plan.yaml").write_text("task_id: password-reset\nsteps: []\n", encoding="utf-8")

    result = advance_stage(
        root_dir,
        "RED_TEST",
        step_id="red-001",
    )

    state = result["state"]
    assert state["stage"] == "RED_TEST"
    assert state["current_step"] == "red-001"


def test_planning_cannot_exit_without_updated_plan_yaml() -> None:
    """Test that leaving PLANNING requires plan.yaml to be created or updated in the stage."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="PLANNING")

    try:
        advance_stage(root_dir, "RED_TEST", step_id="red-001")
    except RuntimeError as exc:
        assert ".agent/plan.yaml" in str(exc)
    else:
        raise AssertionError("Expected PLANNING exit to be blocked without plan.yaml")


def test_ready_to_summarize_is_blocked_without_successful_verification() -> None:
    """Test that ready to summarize is blocked without successful verification."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="VERIFY", remaining_steps=[])

    try:
        ready_to_summarize(root_dir)
    except RuntimeError as exc:
        assert "last_verification" in str(exc)
    else:
        raise AssertionError("Expected ready-to-summarize to fail")


def test_ready_to_summarize_is_blocked_when_plan_has_nonterminal_steps() -> None:
    """Test that ready to summarize is blocked when plan has nonterminal steps."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: write red test\n"
        "    status: done\n"
        "  - name: green-001\n"
        "    description: implement fix\n"
        "    status: in_progress\n",
        encoding="utf-8",
    )
    write_state(
        root_dir,
        task_id="password-reset",
        stage="VERIFY",
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-12T10:00:00Z",
        },
    )

    try:
        ready_to_summarize(root_dir)
    except RuntimeError as exc:
        assert "all plan steps must be done or failed" in str(exc)
    else:
        raise AssertionError("Expected ready-to-summarize to fail")


def test_mark_done_is_blocked_unless_can_finalize_passes() -> None:
    """Test that mark done is blocked unless can finalize passes."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="READY_TO_SUMMARIZE", can_finalize=False)

    try:
        mark_done(root_dir)
    except RuntimeError as exc:
        assert "can-finalize must pass" in str(exc)
    else:
        raise AssertionError("Expected mark-done to fail")


def test_needs_failure_analysis_cannot_exit_without_artifact() -> None:
    """Test that needs failure analysis cannot exit without artifact."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="password-reset",
        stage="NEEDS_FAILURE_ANALYSIS",
        current_step="green-001",
        remaining_steps=["green-001"],
    )

    try:
        advance_stage(root_dir, "GREEN_IMPL", step_id="green-001")
    except RuntimeError as exc:
        assert "failure-analysis.md" in str(exc)
    else:
        raise AssertionError("Expected transition to be blocked")


def test_review_artifact_must_be_updated_after_entering_review() -> None:
    """Test that a stale review artifact from before REVIEW does not satisfy exit gating."""
    root_dir = make_temp_repo()
    review_artifact = root_dir / ".agent" / "artifacts" / "review.md"
    review_artifact.write_text('{"status":"old"}\n', encoding="utf-8")
    write_state(
        root_dir,
        task_id="password-reset",
        stage="GREEN_IMPL",
        current_step="green-001",
        remaining_steps=["green-001"],
    )

    advance_stage(root_dir, "REVIEW")

    try:
        advance_stage(root_dir, "VERIFY", step_id="green-001")
    except RuntimeError as exc:
        assert "review.md" in str(exc)
        assert "updated after entering REVIEW" in str(exc)
    else:
        raise AssertionError("Expected stale review artifact to fail")

    previous_mtime = review_artifact.stat().st_mtime_ns
    review_artifact.write_text('{"status":"fresh"}\n', encoding="utf-8")
    os.utime(review_artifact, ns=(previous_mtime + 1_000_000, previous_mtime + 1_000_000))
    result = advance_stage(root_dir, "VERIFY", step_id="green-001")
    assert result["state"]["stage"] == "VERIFY"


def test_done_cannot_be_advanced_further() -> None:
    """Test that done cannot be advanced further."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="DONE", can_finalize=True)

    try:
        advance_stage(root_dir, "CLARIFYING")
    except RuntimeError as exc:
        assert "DONE cannot transition" in str(exc)
    else:
        raise AssertionError("Expected DONE transition to fail")


def test_transition_appends_event() -> None:
    """Test that transition appends event."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="CLARIFYING")

    advance_stage(root_dir, "PLANNING")

    events = read_events(root_dir)
    assert events[-1]["hook"] == "WorkflowTransition"
    assert events[-1]["from_stage"] == "CLARIFYING"
    assert events[-1]["to_stage"] == "PLANNING"


def test_green_impl_cannot_advance_directly_to_verify() -> None:
    """Test that green impl cannot advance directly to verify."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="password-reset",
        stage="GREEN_IMPL",
        current_step="green-001",
        completed_steps=["red-001"],
        remaining_steps=["green-001"],
    )

    try:
        advance_stage(root_dir, "VERIFY")
    except RuntimeError as exc:
        assert "Illegal transition" in str(exc)
    else:
        raise AssertionError("Expected GREEN_IMPL -> VERIFY to fail")


def test_verify_can_advance_directly_to_red_test_and_green_impl() -> None:
    """Test that verify can advance directly to red test and green impl."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="VERIFY", current_step="verify-001")

    result = advance_stage(root_dir, "RED_TEST")
    assert result["state"]["stage"] == "RED_TEST"

    write_state(root_dir, task_id="password-reset", stage="VERIFY", current_step="verify-001")
    result = advance_stage(root_dir, "GREEN_IMPL")
    assert result["state"]["stage"] == "GREEN_IMPL"


def test_cli_representative_flow_from_start_to_done() -> None:
    """Test that cli representative flow from start to done."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: write red test\n"
        "    status: in_progress\n"
        "  - name: green-001\n"
        "    description: implement fix\n"
        "    status: pending\n",
        encoding="utf-8",
    )
    assert invoke_cli(root_dir, ["start-task", "password-reset"])[0] == 0
    assert invoke_cli(root_dir, ["advance-stage", "--to", "PLANNING"])[0] == 0
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: write red test\n"
        "    status: in_progress\n"
        "  - name: green-001\n"
        "    description: implement fix\n"
        "    status: pending\n",
        encoding="utf-8",
    )
    plan_path = root_dir / ".agent" / "plan.yaml"
    plan_mtime = plan_path.stat().st_mtime_ns
    os.utime(plan_path, ns=(plan_mtime + 1_000_000, plan_mtime + 1_000_000))
    assert invoke_cli(
        root_dir,
        ["advance-stage", "--to", "RED_TEST", "--step", "red-001"],
    )[0] == 0
    assert invoke_cli(
        root_dir,
        [
            "complete-step",
            "red-001",
            "--next-step",
            "green-001",
        ],
    )[0] == 0
    assert invoke_cli(root_dir, ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"])[0] == 0

    code, _ = invoke_cli(root_dir, ["advance-stage", "--to", "REVIEW"])
    assert code == 0
    (root_dir / ".agent" / "artifacts" / "review.md").write_text("# Review\n", encoding="utf-8")
    assert invoke_cli(root_dir, ["complete-step", "green-001"])[0] == 0
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
    (root_dir / ".agent" / "artifacts" / "summary.md").write_text(
        "Implemented password reset flow and verified with pytest.\n",
        encoding="utf-8",
    )
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: write red test\n"
        "    status: done\n"
        "  - name: green-001\n"
        "    description: implement fix\n"
        "    status: done\n",
        encoding="utf-8",
    )
    assert invoke_cli(root_dir, ["mark-done"])[0] == 0
    assert load_state(root_dir)["stage"] == "DONE"


def test_cli_failed_verify_requires_failure_analysis_then_allows_reentry() -> None:
    """Test that cli failed verify requires failure analysis then allows reentry."""
    root_dir = make_temp_repo()
    write_state(root_dir, task_id="password-reset", stage="VERIFY", current_step="verify-001")
    log_path = ".agent/artifacts/final-verification.log"
    (root_dir / log_path).write_text("boom\n", encoding="utf-8")

    code, _ = invoke_cli(root_dir, ["record-command", "--cmd", "pytest", "--exit-code", "1", "--log", log_path])
    assert code == 0
    assert load_state(root_dir)["stage"] == "NEEDS_FAILURE_ANALYSIS"

    code, payload = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"],
    )
    assert code == 1
    assert "failure-analysis.md" in payload["error"]

    (root_dir / ".agent" / "artifacts" / "failure-analysis.md").write_text("## Failure Summary\n", encoding="utf-8")
    code, _ = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"],
    )
    assert code == 0


def test_failure_analysis_artifact_must_be_updated_in_current_stage() -> None:
    """Test that a stale failure-analysis artifact must be refreshed after entering analysis stage."""
    root_dir = make_temp_repo()
    analysis_artifact = root_dir / ".agent" / "artifacts" / "failure-analysis.md"
    analysis_artifact.write_text("## Failure Summary\nold\n", encoding="utf-8")
    write_state(
        root_dir,
        task_id="password-reset",
        stage="VERIFY",
        current_step="verify-001",
    )
    invoke_cli(root_dir, ["record-command", "--cmd", "pytest", "--exit-code", "1", "--log", ".agent/artifacts/final-verification.log"])

    code, payload = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"],
    )
    assert code == 1
    assert "failure-analysis.md" in payload["error"]
    assert "updated after entering NEEDS_FAILURE_ANALYSIS" in payload["error"]

    previous_mtime = analysis_artifact.stat().st_mtime_ns
    analysis_artifact.write_text("## Failure Summary\nfresh\n", encoding="utf-8")
    os.utime(analysis_artifact, ns=(previous_mtime + 1_000_000, previous_mtime + 1_000_000))
    code, _ = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"],
    )
    assert code == 0


def test_failure_analysis_artifact_format_is_checked_when_configured() -> None:
    """Test that required artifacts can enforce a configured content regex."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        task_id="password-reset",
        stage="VERIFY",
        current_step="verify-001",
    )
    invoke_cli(root_dir, ["record-command", "--cmd", "pytest", "--exit-code", "1", "--log", ".agent/artifacts/final-verification.log"])

    analysis_artifact = root_dir / ".agent" / "artifacts" / "failure-analysis.md"
    analysis_artifact.write_text("missing heading\n", encoding="utf-8")
    current_mtime = analysis_artifact.stat().st_mtime_ns
    os.utime(analysis_artifact, ns=(current_mtime + 1_000_000, current_mtime + 1_000_000))

    code, payload = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"],
    )
    assert code == 1
    assert payload["error"].endswith("failure-analysis.md must start with the Failure Summary section.")

    previous_mtime = analysis_artifact.stat().st_mtime_ns
    analysis_artifact.write_text("## Failure Summary\nvalid\n", encoding="utf-8")
    os.utime(analysis_artifact, ns=(previous_mtime + 1_000_000, previous_mtime + 1_000_000))
    code, _ = invoke_cli(
        root_dir,
        ["advance-stage", "--to", "GREEN_IMPL", "--step", "green-001"],
    )
    assert code == 0
