"""Tests for test gates."""
from agent_guard.gates import can_finalize

from .helpers import make_temp_repo, write_state


def test_finalization_is_blocked_when_verification_is_missing() -> None:
    """Test that finalization is blocked when verification is missing."""
    root_dir = make_temp_repo()
    write_state(root_dir, can_finalize=True)

    result = can_finalize(root_dir)
    assert result["decision"] == "block"
    assert "last_verification.exit_code must be 0" in result["reasons"]


def test_finalization_is_blocked_when_plan_is_missing() -> None:
    """Test that finalization is blocked when plan.yaml is missing."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        can_finalize=True,
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-14T10:00:00Z",
        },
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "block"
    assert "all plan steps must be done or failed" in "\n".join(result["reasons"]).lower()


def test_finalization_is_blocked_when_plan_has_nonterminal_steps() -> None:
    """Test that finalization is blocked when plan has nonterminal steps."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: add failing test\n"
        "    status: done\n"
        "  - name: green-001\n"
        "    description: implement fix\n"
        "    status: in_progress\n",
        encoding="utf-8",
    )
    write_state(
        root_dir,
        can_finalize=True,
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-14T10:00:00Z",
        },
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "block"
    assert "all plan steps must be done or failed" in "\n".join(result["reasons"]).lower()


def test_finalization_allows_plan_when_all_steps_are_done_or_failed() -> None:
    """Test that finalization allows plan when all steps are done or failed."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - id: red-001\n"
        "    stage: RED_TEST\n"
        "    goal: add failing test\n"
        "    status: done\n"
        "  - id: green-001\n"
        "    stage: GREEN_IMPL\n"
        "    goal: implement fix\n"
        "    status: failed\n",
        encoding="utf-8",
    )
    write_state(
        root_dir,
        can_finalize=True,
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-14T10:00:00Z",
        },
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "allow"
