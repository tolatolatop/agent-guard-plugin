"""Tests for test workflow spec."""
from pathlib import Path

import yaml

from agent_guard.workflow_spec import (
    canonical_completion_ready_stage,
    canonical_completion_stage,
    canonical_entry_stage,
    canonical_stage_plan_mode,
    canonical_stage_spec,
    canonical_workflow_spec,
    failure_policy,
    finalization_policy,
    install_defaults,
    load_workflow_spec,
    normalize_workflow_spec,
    packaged_workflow_path,
    path_policy,
    session_start_defaults,
    source_workflow_path,
    stage_required_artifact_rules,
    stage_policy_view,
    stage_policy_roles,
    stage_display_artifacts,
    stage_entry_conditions,
    stage_exit_conditions,
    stage_forbid_needs_human_display,
    transition_graph_mermaid,
    stage_write_policy,
    workflow_policy_view,
    workflow_policy_roles,
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
        ".agent/artifacts/review.md must exist",
    ]


def test_green_impl_entry_conditions_are_empty() -> None:
    """Test that green impl entry conditions are empty."""
    assert stage_entry_conditions("GREEN_IMPL", "RED_TEST") == []


def test_planning_exit_conditions_include_required_plan_artifact() -> None:
    """Test that leaving planning requires an updated plan.yaml artifact."""
    conditions = stage_exit_conditions("PLANNING")

    assert conditions["RED_TEST"] == [
        ".agent/plan.yaml must exist",
    ]


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
    assert session_start_defaults()["navigator_skill"] == "using-workflow"
    assert install_defaults()["skill_match"] == []
    assert install_defaults()["skill_exclude_match"] == []
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


def test_stage_required_artifact_rules_support_optional_regex_validation() -> None:
    """Test that required artifact rules expose optional format validation fields."""
    rules = stage_required_artifact_rules("NEEDS_FAILURE_ANALYSIS")

    assert rules == [
        {
            "path": ".agent/artifacts/failure-analysis.md",
            "matches": "^## Failure Summary",
            "message": "failure-analysis.md must start with the Failure Summary section.",
        }
    ]


def test_stage_policy_view_exposes_grouped_ddd_shape() -> None:
    """Test that one stage can be read through the grouped DSL view."""
    stage = stage_policy_view("RED_TEST")

    assert stage["intent"]["goal"] == "Create a failing test that proves the missing behavior."
    assert stage["permissions"]["write"]["allow"] == ["tests/**"]
    assert stage["permissions"]["write"]["deny"] == ["src/**", ".agent/plan.yaml"]
    assert stage["permissions"]["commands"]["complete_step"] == "allow"
    assert stage["permissions"]["handoff"]["human_stop"] == "deny"
    assert stage["transitions"]["to"] == ["GREEN_IMPL", "NEEDS_FAILURE_ANALYSIS"]
    assert stage["evidence"]["expected"] == [".agent/artifacts/red-test.log"]
    assert stage["evidence"]["required"] == []


def test_workflow_policy_view_exposes_grouped_globals_and_stages() -> None:
    """Test that the grouped workflow view includes globals and stage policies."""
    workflow = workflow_policy_view()

    assert workflow["workflow"]["id"] == "standard-ddd-example"
    assert ".github/**" in workflow["globals"]["paths"]["sensitive"]
    assert workflow["globals"]["failures"]["repeat_threshold"] == 2
    assert "successful_last_verification" in workflow["globals"]["finalization"]["require"]
    assert workflow["globals"]["session_start"]["navigator_skill"] == "using-workflow"
    assert workflow["globals"]["install"]["skills"]["match"] == []
    assert "RED_TEST" in workflow["stages"]


def test_stage_policy_roles_distinguish_soft_and_hard_concerns() -> None:
    """Test that grouped stage views expose role annotations."""
    roles = stage_policy_roles("RED_TEST")

    assert roles["intent"] == "soft_prompt"
    assert roles["permissions"]["write"] == "hard_gate"
    assert roles["permissions"]["actions"] == "soft_prompt"
    assert roles["transitions"] == "hard_gate"
    assert roles["evidence"]["required"] == "hard_gate"
    assert roles["evidence"]["expected"] == "soft_prompt"


def test_workflow_policy_roles_mark_global_gate_types() -> None:
    """Test that grouped workflow roles distinguish global hard gates from prompts."""
    roles = workflow_policy_roles()

    assert roles["workflow"] == "soft_prompt"
    assert roles["globals"]["paths"] == "hard_gate"
    assert roles["globals"]["finalization"] == "hard_gate"
    assert roles["globals"]["wizard"] == "soft_prompt"
    assert roles["globals"]["session_start"] == "soft_prompt"
    assert roles["globals"]["install"] == "soft_prompt"


def test_normalize_workflow_spec_accepts_grouped_dsl_shape() -> None:
    """Test that grouped DSL input is normalized into the flat internal shape."""
    grouped = {
        "version": 1,
        "workflow": {
            "id": "grouped-example",
            "title": "Grouped Example",
            "description": "DSL compatibility test",
        },
        "globals": {
            "paths": {
                "protected": [".agent/state.json"],
                "sensitive": [".github/**"],
            },
            "failures": {
                "repeat_threshold": 2,
                "fingerprint_roots": ["src", "tests"],
            },
            "finalization": {
                "require": ["successful_last_verification"],
                "messages": {
                    "successful_last_verification": "last_verification.exit_code must be 0",
                },
            },
            "wizard": {
                "start_stages": ["RED_TEST"],
            },
            "session_start": {
                "navigator_skill": "workflow-core",
            },
            "install": {
                "skills": {
                    "match": ["workflow"],
                    "exclude_match": ["failure"],
                }
            },
        },
        "stages": {
            "RED_TEST": {
                "intent": {
                    "goal": "Create a failing test.",
                },
                "permissions": {
                    "write": {
                        "allow": ["tests/**"],
                        "deny": ["src/**"],
                    },
                    "actions": {
                        "allow": ["write tests"],
                        "deny": ["write production code"],
                    },
                    "commands": {
                        "complete_step": "allow",
                    },
                    "handoff": {
                        "human_stop": "deny",
                        "deny_message": "stay in stage",
                    },
                },
                "transitions": {
                    "to": ["GREEN_IMPL"],
                    "enter_when": [],
                },
                "evidence": {
                    "expected": [".agent/artifacts/red-test.log"],
                    "required": [],
                },
            },
        },
    }

    normalized = normalize_workflow_spec(grouped)

    assert normalized["metadata"]["id"] == "grouped-example"
    assert normalized["path_policy"]["protected_paths"] == [".agent/state.json"]
    assert normalized["path_policy"]["sensitive_paths"] == [".github/**"]
    assert normalized["failure_policy"]["fingerprint_roots"] == ["src", "tests"]
    assert normalized["finalization_policy"]["required_rules"] == ["successful_last_verification"]
    assert normalized["wizard_defaults"]["start_stages"] == ["RED_TEST"]
    assert normalized["session_start_defaults"]["navigator_skill"] == "workflow-core"
    assert normalized["install_defaults"]["skill_match"] == ["workflow"]
    assert normalized["install_defaults"]["skill_exclude_match"] == ["failure"]
    assert normalized["stages"]["RED_TEST"]["goal"] == "Create a failing test."
    assert normalized["stages"]["RED_TEST"]["write_policy"]["writable_paths"] == ["tests/**"]
    assert normalized["stages"]["RED_TEST"]["allows_complete_step"] is True
    assert normalized["stages"]["RED_TEST"]["forbid_needs_human"]["display"] == "stay in stage"
    assert normalized["stages"]["RED_TEST"]["artifacts_required"] == []


def test_grouped_workflow_example_file_normalizes_and_validates() -> None:
    """Test that the checked-in grouped workflow example stays parseable."""
    example_path = Path(__file__).resolve().parents[1] / "docs" / "grouped-workflow.example.yaml"
    payload = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    normalized = normalize_workflow_spec(payload)

    assert normalized["metadata"]["id"] == "standard-ddd-example"
    assert normalized["stages"]["REVIEW"]["artifacts_required"] == [{"path": ".agent/artifacts/review.md"}]
    assert normalized["stages"]["READY_TO_SUMMARIZE"]["allowed_next_stages"] == ["DONE"]


def test_canonical_workflow_projects_legacy_grouped_dsl() -> None:
    """Test that the legacy grouped workflow is projected into the canonical Phase 1 model."""
    workflow = canonical_workflow_spec()

    assert workflow["workflow"]["entry"] == "CLARIFYING"
    assert workflow["globals"]["finalize"]["require"] == [
        {"rule": "no_running_jobs"},
        {"rule": "successful_last_verification"},
        {"rule": "can_finalize_flag"},
        {"rule": "all_plan_steps_terminal"},
    ]
    assert workflow["stages"]["PLANNING"]["plan"] == "create"
    assert workflow["stages"]["GREEN_IMPL"]["plan"] == "follow"
    assert workflow["stages"]["READY_TO_SUMMARIZE"]["plan"] == "complete"
    assert workflow["stages"]["PLANNING"]["exit"] == [".agent/plan.yaml"]
    assert workflow["stages"]["NEEDS_FAILURE_ANALYSIS"]["exit"] == [
        {
            "path": ".agent/artifacts/failure-analysis.md",
            "matches": "^## Failure Summary",
            "message": "failure-analysis.md must start with the Failure Summary section.",
        }
    ]


def test_canonical_helpers_resolve_legacy_completion_and_entry_stages() -> None:
    """Test that canonical helper APIs preserve the legacy workflow behavior."""
    assert canonical_entry_stage() == "CLARIFYING"
    assert canonical_completion_ready_stage() == "READY_TO_SUMMARIZE"
    assert canonical_completion_stage() == "DONE"
    assert canonical_stage_plan_mode("VERIFY") == "follow"
    assert canonical_stage_spec("DONE")["final"] is True


def test_load_workflow_spec_reports_friendly_message_for_invalid_yaml(monkeypatch, tmp_path: Path) -> None:
    """Test that invalid workflow YAML reports a repair-required message."""
    workflow_file = tmp_path / ".workflow.yaml"
    workflow_file.write_text("workflow: [\n", encoding="utf-8")
    load_workflow_spec.cache_clear()
    monkeypatch.setattr("agent_guard.workflow_spec.packaged_workflow_path", lambda: workflow_file)
    monkeypatch.setattr("agent_guard.workflow_spec.source_workflow_path", lambda: workflow_file)

    try:
        load_workflow_spec()
    except RuntimeError as exc:
        assert ".workflow.yaml appears damaged" in str(exc)
        assert "cannot continue" in str(exc)
    else:
        raise AssertionError("Expected invalid workflow YAML to fail")
    finally:
        load_workflow_spec.cache_clear()


def test_load_workflow_spec_reports_friendly_message_for_non_mapping(monkeypatch, tmp_path: Path) -> None:
    """Test that non-mapping workflow documents report a repair-required message."""
    workflow_file = tmp_path / ".workflow.yaml"
    workflow_file.write_text("- bad\n", encoding="utf-8")
    load_workflow_spec.cache_clear()
    monkeypatch.setattr("agent_guard.workflow_spec.packaged_workflow_path", lambda: workflow_file)
    monkeypatch.setattr("agent_guard.workflow_spec.source_workflow_path", lambda: workflow_file)

    try:
        load_workflow_spec()
    except RuntimeError as exc:
        assert ".workflow.yaml appears damaged" in str(exc)
        assert "cannot continue" in str(exc)
        assert "top-level document must be a YAML mapping" in str(exc)
    else:
        raise AssertionError("Expected non-mapping workflow YAML to fail")
    finally:
        load_workflow_spec.cache_clear()
