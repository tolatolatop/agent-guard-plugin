from agent_guard.plan import load_plan, load_plan_summary, plan_steps

from .helpers import make_temp_repo


def test_plan_steps_accepts_minimal_name_description_status_schema() -> None:
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "task_id: password-reset\n"
        "steps:\n"
        "  - name: red-001\n"
        "    description: Add a failing password reset test\n"
        "    status: done\n",
        encoding="utf-8",
    )

    assert load_plan(root_dir)["task_id"] == "password-reset"
    assert plan_steps(root_dir) == [
        {
            "name": "red-001",
            "description": "Add a failing password reset test",
            "status": "done",
        }
    ]
    assert load_plan_summary(root_dir) == {"exists": True, "includesReview": False, "step_count": 1}


def test_plan_steps_rejects_legacy_scope_fields_without_minimal_fields() -> None:
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "plan.yaml").write_text(
        "steps:\n"
        "  - id: red-001\n"
        "    stage: RED_TEST\n",
        encoding="utf-8",
    )

    try:
        plan_steps(root_dir)
    except RuntimeError as exc:
        assert "field name" in str(exc)
    else:
        raise AssertionError("Expected minimal plan schema validation to fail")
