from agent_guard.workflow_spec import complete_step_allowed_from_stages


def test_complete_step_allowed_stages_are_declared_in_workflow_spec() -> None:
    assert complete_step_allowed_from_stages() == ["RED_TEST", "GREEN_IMPL", "REVIEW", "VERIFY"]
