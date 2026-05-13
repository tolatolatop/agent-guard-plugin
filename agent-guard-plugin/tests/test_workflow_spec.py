from agent_guard.workflow_spec import stage_exit_conditions


def test_ready_to_summarize_exit_conditions_include_required_summary_artifact() -> None:
    conditions = stage_exit_conditions("READY_TO_SUMMARIZE")

    assert conditions["DONE"] == [
        "use mark-done",
        "can-finalize must pass",
        ".agent/artifacts/summary.md must exist",
    ]


def test_needs_failure_analysis_exit_conditions_resolve_required_artifact_placeholder() -> None:
    conditions = stage_exit_conditions("NEEDS_FAILURE_ANALYSIS")

    assert conditions["VERIFY"] == [".agent/artifacts/failure-analysis.md must exist"]
