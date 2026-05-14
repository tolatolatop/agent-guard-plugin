"""Tests for test workflow spec."""
from agent_guard.workflow_spec import (
    stage_entry_conditions,
    stage_exit_conditions,
    stage_forbid_needs_human_display,
)


def test_ready_to_summarize_exit_conditions_follow_done_entry_conditions() -> None:
    """Test that ready to summarize exit conditions follow done entry conditions."""
    conditions = stage_exit_conditions("READY_TO_SUMMARIZE")

    assert conditions["DONE"] == [
        "use mark-done",
        "can-finalize must pass",
    ]


def test_needs_failure_analysis_exit_conditions_resolve_required_artifact_placeholder() -> None:
    """Test that needs failure analysis exit conditions resolve required artifact placeholder."""
    conditions = stage_exit_conditions("NEEDS_FAILURE_ANALYSIS")

    assert conditions["VERIFY"] == [
        ".agent/artifacts/failure-analysis.md must exist",
    ]


def test_review_exit_conditions_include_required_review_artifact() -> None:
    """Test that review exit conditions include required review artifact."""
    conditions = stage_exit_conditions("REVIEW")

    assert conditions["VERIFY"] == [
        ".agent/artifacts/review.json must exist",
    ]


def test_green_impl_entry_conditions_are_empty() -> None:
    """Test that green impl entry conditions are empty."""
    assert stage_entry_conditions("GREEN_IMPL", "RED_TEST") == []


def test_stage_forbid_needs_human_display_is_exposed() -> None:
    """Test that stage forbid needs human display is exposed."""
    assert (
        stage_forbid_needs_human_display("GREEN_IMPL")
        == "Current stage does not allow human intervention; continue advancing the task."
    )
