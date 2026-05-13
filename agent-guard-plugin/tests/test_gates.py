from agent_guard.gates import can_finalize

from .helpers import make_temp_repo, write_state


def test_finalization_is_blocked_when_verification_is_missing() -> None:
    root_dir = make_temp_repo()
    write_state(root_dir, remaining_steps=[], can_finalize=True)

    result = can_finalize(root_dir)
    assert result["decision"] == "block"
    assert "verification" in "\n".join(result["reasons"]).lower()


def test_finalization_is_allowed_only_when_state_is_complete_and_verification_passed() -> None:
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "artifacts" / "summary.md").write_text("done\n", encoding="utf-8")
    write_state(
        root_dir,
        remaining_steps=[],
        can_finalize=True,
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-11T10:00:00Z",
        },
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "allow"


def test_finalization_is_blocked_when_summary_artifact_is_missing() -> None:
    root_dir = make_temp_repo()
    write_state(
        root_dir,
        remaining_steps=[],
        can_finalize=True,
        last_verification={
            "command": "pytest",
            "exit_code": 0,
            "log_path": ".agent/artifacts/final-verification.log",
            "recorded_at": "2026-05-11T10:00:00Z",
        },
    )

    result = can_finalize(root_dir)
    assert result["decision"] == "block"
    assert "summary artifact" in "\n".join(result["reasons"]).lower()
