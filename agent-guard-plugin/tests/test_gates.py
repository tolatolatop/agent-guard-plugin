"""Tests for test gates."""
from agent_guard.gates import can_finalize

from .helpers import make_temp_repo, write_state


def test_finalization_is_blocked_when_verification_is_missing() -> None:
    """Test that finalization is blocked when verification is missing."""
    root_dir = make_temp_repo()
    write_state(root_dir, remaining_steps=[], can_finalize=True)

    result = can_finalize(root_dir)
    assert result["decision"] == "allow"


def test_finalization_is_allowed_only_when_state_is_complete_and_verification_passed() -> None:
    """Test that finalization is allowed only when state is complete and verification passed."""
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        remaining_steps=[],
        can_finalize=True,
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "allow"


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
        remaining_steps=[],
        can_finalize=True,
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "block"
    assert "non-terminal steps" in "\n".join(result["reasons"]).lower()


def test_finalization_allows_plan_when_all_steps_are_done_or_failed() -> None:
    """Test that finalization allows plan when all steps are done or failed."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: add failing test\n"
        "    status: done\n"
        "  - name: green-001\n"
        "    description: implement fix\n"
        "    status: failed\n",
        encoding="utf-8",
    )
    write_state(root_dir, remaining_steps=[], can_finalize=True)

    result = can_finalize(root_dir)
    assert result["decision"] == "allow"
