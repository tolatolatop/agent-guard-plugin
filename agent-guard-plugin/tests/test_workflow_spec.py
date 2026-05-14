"""Tests for test workflow spec."""
from agent_guard.workflow_spec import (
    failure_policy,
    finalization_policy,
    path_policy,
    stage_display_artifacts,
    stage_entry_conditions,
    stage_exit_conditions,
    stage_forbid_needs_human_display,
    transition_graph_mermaid,
    stage_write_policy,
    wizard_defaults,
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


def test_policy_sections_are_loaded_from_workflow_spec() -> None:
    """Test that top-level workflow policies are available."""
    assert ".github/**" in path_policy()["sensitive_paths"]
    assert failure_policy()["repeat_threshold"] == 2
    assert "successful_last_verification" in finalization_policy()["required_rules"]
    assert wizard_defaults()["start_stages"] == ["CLARIFYING", "PLANNING", "RED_TEST", "GREEN_IMPL"]
    assert stage_write_policy("RED_TEST")["writable_paths"] == ["tests/**"]


def test_transition_graph_mermaid_is_generated_from_stage_transitions() -> None:
    """Test that transition graph Mermaid is generated from the stage transition map."""
    graph = transition_graph_mermaid()

    assert graph.startswith("flowchart TD")
    assert "  IDLE --> CLARIFYING" in graph
    assert "  GREEN_IMPL --> REVIEW" in graph
    assert "  READY_TO_SUMMARIZE --> DONE" in graph


def test_stage_display_artifacts_merge_required_and_expected_without_duplicates() -> None:
    """Test that display artifacts show required items without duplicate expected entries."""
    assert stage_display_artifacts("NEEDS_FAILURE_ANALYSIS") == [
        ".agent/artifacts/failure-analysis.md",
    ]
