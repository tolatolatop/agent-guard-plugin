"""Tests for test workflow spec."""
from pathlib import Path

import yaml

from agent_guard.workflow_spec import (
    completion_ready_stage,
    completion_stage,
    discover_workflow_ids,
    expected_failure_stage,
    failure_analysis_stage,
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
    stage_entry_conditions_from_spec,
    stage_exit_conditions,
    stage_forbid_needs_human_display,
    stage_human_allowed,
    stage_plan_mode,
    stage_stop_allowed,
    transition_graph_mermaid,
    validate_workflow_spec,
    verification_stage,
    stage_write_policy,
    workflow_entry_stage,
    workflow_policy_view,
    workflow_policy_roles,
    workflow_stage_for_role,
    workflow_stage_roles,
    wizard_defaults,
)


def test_new_runtime_role_api_resolves_default_workflow_roles() -> None:
    """Runtime stage-role helpers should expose workflow roles without projection callers."""
    assert workflow_entry_stage() == "CLARIFYING"
    assert workflow_stage_roles() == {
        "verification": "VERIFY",
        "expected_failure": "RED_TEST",
        "failure_analysis": "NEEDS_FAILURE_ANALYSIS",
        "completion_ready": "READY_TO_SUMMARIZE",
        "completion": "DONE",
        "human_handoff": "NEEDS_HUMAN",
    }
    assert workflow_stage_for_role("verification") == "VERIFY"
    assert verification_stage() == "VERIFY"
    assert expected_failure_stage() == "RED_TEST"
    assert failure_analysis_stage() == "NEEDS_FAILURE_ANALYSIS"
    assert completion_ready_stage() == "READY_TO_SUMMARIZE"
    assert completion_stage() == "DONE"


def test_new_runtime_stage_api_exposes_plan_and_handoff_flags() -> None:
    """Runtime stage helpers should read plan/stop/human behavior through v2-facing names."""
    assert stage_plan_mode("VERIFY") == "advance"
    assert stage_stop_allowed("VERIFY") is False
    assert stage_human_allowed("VERIFY") is False
    assert stage_stop_allowed("DONE") is True
    assert stage_human_allowed("DONE") is True


def test_ready_to_summarize_exit_conditions_follow_done_entry_conditions() -> None:
    """Test that ready to summarize exit conditions follow done entry conditions."""
    conditions = stage_exit_conditions("READY_TO_SUMMARIZE")

    assert conditions["DONE"] == [
        ".agent/artifacts/summary.md must exist",
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


def test_designing_exit_conditions_include_required_design_artifact() -> None:
    """Test that leaving DESIGNING requires the design artifact."""
    conditions = stage_exit_conditions("DESIGNING")

    assert conditions["PLANNING"] == [
        ".agent/artifacts/DESIGN.md must exist",
        "active task exists",
    ]


def test_verify_exit_conditions_include_final_verification_log() -> None:
    """Test that leaving VERIFY requires the final verification log artifact."""
    conditions = stage_exit_conditions("VERIFY")

    assert conditions["READY_TO_SUMMARIZE"] == [
        ".agent/artifacts/final-verification.log must exist",
        "must run pytest during VERIFY",
        "pytest must succeed during VERIFY",
        "use ready-to-summarize",
        "no running jobs",
        "all plan steps must be done or failed",
        "can_finalize enabled only through ready-to-summarize",
    ]


def test_red_test_exit_conditions_include_pytest_command_requirement() -> None:
    """Test that leaving RED_TEST requires running pytest in the current stage."""
    conditions = stage_exit_conditions("RED_TEST")

    assert conditions["GREEN_IMPL"] == [
        "must run pytest during RED_TEST",
    ]


def test_green_impl_entry_conditions_are_empty() -> None:
    """Test that green impl entry conditions are empty."""
    assert stage_entry_conditions("GREEN_IMPL", "RED_TEST") == []


def test_stage_entry_conditions_preserve_path_based_checks() -> None:
    """Path-based enter checks should stay machine-readable after normalization."""
    spec = normalize_workflow_spec(
        {
            "version": 2,
            "workflow": {"id": "entry-checks", "title": "Entry Checks", "entry": "PREP"},
            "globals": {
                "protected": [],
                "sensitive": [],
                "failures": {},
                "finalize": {"require": []},
                "wizard": {"start_stages": ["PREP"]},
                "session_start": {"navigator_skill": "using-workflow"},
                "install": {"skills": {"match": [], "exclude_match": []}},
            },
            "stages": {
                "PREP": {
                    "goal": "prepare",
                    "plan": "deny",
                    "allow": {"write": [], "actions": [], "stop": True, "human": True},
                    "deny": {"write": [], "actions": []},
                    "enter": [],
                    "exit": [],
                    "expect": [],
                    "next": ["READY"],
                },
                "READY": {
                    "goal": "ready",
                    "plan": "deny",
                    "allow": {"write": [], "actions": [], "stop": True, "human": True},
                    "deny": {"write": [], "actions": []},
                    "enter": [
                        "output/**",
                        {"path": "output/*/review.md", "matches": "^# Review", "display": "review must start with # Review"},
                        {"display": "reminder only"},
                    ],
                    "exit": [],
                    "expect": [],
                    "next": [],
                },
            },
        }
    )

    assert stage_entry_conditions_from_spec(spec, "READY") == [
        {"path": "output/**", "display": "output/** must exist"},
        {"path": "output/*/review.md", "matches": "^# Review", "display": "review must start with # Review"},
        {"display": "reminder only"},
    ]


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
            "display": "failure-analysis.md must start with the Failure Summary section.",
        }
    ]


def test_required_artifact_display_is_preserved() -> None:
    """Test that required artifact display text is preserved."""
    spec = {
        "version": 2,
        "workflow": {"id": "artifact-display", "title": "Artifact Display", "entry": "REVIEW"},
        "globals": {"protected": [], "sensitive": [], "failures": {}, "finalize": {"require": []}, "session_start": {}},
        "stages": {
            "REVIEW": {
                "goal": "review",
                "plan": "advance",
                "allow": {"write": [], "actions": [], "stop": False, "human": False},
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [
                    {
                        "path": ".agent/artifacts/review.md",
                        "matches": "^# Review",
                        "display": "review.md must start with a heading.",
                    }
                ],
                "expect": [],
                "next": [],
            }
        },
    }

    normalized = normalize_workflow_spec(spec)

    assert normalized["stages"]["REVIEW"]["artifacts_required"] == [
        {
            "path": ".agent/artifacts/review.md",
            "matches": "^# Review",
            "display": "review.md must start with a heading.",
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


def _minimal_v2_workflow() -> dict[str, object]:
    return {
        "version": 2,
        "workflow": {"id": "minimal", "title": "Minimal", "entry": "ONLY"},
        "globals": {
            "protected": [],
            "sensitive": [],
            "failures": {},
            "finalize": {"require": []},
            "session_start": {"navigator_skill": "using-workflow"},
        },
        "stages": {
            "ONLY": {
                "goal": "Only stage.",
                "plan": "deny",
                "allow": {"write": [], "actions": [], "stop": True, "human": True},
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [],
                "expect": [],
                "next": [],
            },
        },
    }


def _assert_unsupported_workflow_schema(spec: dict[str, object], expected: str) -> None:
    try:
        normalize_workflow_spec(spec)
    except RuntimeError as exc:
        assert "Unsupported workflow schema" in str(exc)
        assert "docs/workflow-schema.md" in str(exc)
        assert expected in str(exc)
    else:
        raise AssertionError("Expected unsupported workflow schema to fail")


def test_version_1_workflow_schema_is_rejected() -> None:
    """Test that version 1 workflows are not normalized."""
    spec = _minimal_v2_workflow()
    spec["version"] = 1

    _assert_unsupported_workflow_schema(spec, "version must be 2")


def test_legacy_globals_paths_schema_is_rejected() -> None:
    """Test that old globals.paths workflows are rejected."""
    spec = _minimal_v2_workflow()
    spec["globals"] = {
        "paths": {"protected": [".agent/state.json"], "sensitive": []},
        "failures": {},
        "finalize": {"require": []},
        "session_start": {"navigator_skill": "using-workflow"},
    }

    _assert_unsupported_workflow_schema(spec, "legacy globals.paths")


def test_legacy_globals_finalization_schema_is_rejected() -> None:
    """Test that old globals.finalization workflows are rejected."""
    spec = _minimal_v2_workflow()
    spec["globals"] = {
        "protected": [],
        "sensitive": [],
        "failures": {},
        "finalization": {"require": []},
        "session_start": {"navigator_skill": "using-workflow"},
    }

    _assert_unsupported_workflow_schema(spec, "legacy globals.finalization")


def test_legacy_stage_shape_is_rejected() -> None:
    """Test that grouped legacy stage fields are rejected."""
    spec = _minimal_v2_workflow()
    spec["stages"] = {
        "ONLY": {
            "intent": {"goal": "Old goal"},
            "permissions": {"write": {"allow": [], "deny": []}},
            "transitions": {"to": []},
            "evidence": {"expected": [], "required": []},
        }
    }

    _assert_unsupported_workflow_schema(spec, "legacy stage field ONLY.intent")


def test_workflow_roles_must_reference_existing_stages() -> None:
    """Test that explicit workflow role targets are validated."""
    spec = _minimal_v2_workflow()
    spec["workflow"] = {"id": "bad-role", "title": "Bad Role", "entry": "ONLY", "roles": {"verification": "MISSING"}}
    normalized = normalize_workflow_spec(spec)

    try:
        validate_workflow_spec(normalized)
    except RuntimeError as exc:
        assert "workflow.roles references unknown stage" in str(exc)
        assert "verification=MISSING" in str(exc)
    else:
        raise AssertionError("Expected invalid workflow role target to fail")


def test_explicit_workflow_roles_override_inferred_roles(monkeypatch, tmp_path: Path) -> None:
    """Test that workflow.roles can explicitly bind runtime roles."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    spec = _minimal_v2_workflow()
    spec["workflow"] = {"id": "role-override", "title": "Role Override", "entry": "ONLY", "roles": {"verification": "ONLY"}}
    (user_dir / "default.workflow.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    monkeypatch.setattr("agent_guard.workflow_spec.user_workflow_dirs", lambda: [user_dir])
    load_workflow_spec.cache_clear()

    try:
        assert workflow_stage_roles()["verification"] == "ONLY"
        assert verification_stage() == "ONLY"
    finally:
        load_workflow_spec.cache_clear()


def test_normalize_workflow_spec_applies_plan_create_defaults_in_current_dsl() -> None:
    """Test that plan:create injects plan.yaml write and artifact defaults."""
    spec = {
        "version": 2,
        "workflow": {
            "id": "current-example",
            "title": "Current Example",
            "description": "Current DSL test",
            "entry": "PLANNING",
        },
        "globals": {
            "protected": [".agent/state.json"],
            "sensitive": [".github/**"],
            "failures": {
                "repeat_threshold": 2,
                "fingerprint_roots": ["src", "tests"],
            },
            "finalize": {
                "require": [{"rule": "successful_last_verification"}],
                "messages": {
                    "successful_last_verification": "last_verification.exit_code must be 0",
                },
            },
            "wizard": {
                "start_stages": ["PLANNING"],
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
            "PLANNING": {
                "goal": "Create a plan.",
                "plan": "create",
                "allow": {
                    "write": [],
                    "actions": ["write or refine plan.yaml"],
                    "stop": True,
                    "human": True,
                },
                "deny": {
                    "write": [],
                    "actions": ["execute unplanned broad changes"],
                },
                "enter": [],
                "exit": [],
                "expect": [],
                "next": [],
            },
        },
    }

    normalized = normalize_workflow_spec(spec)

    assert normalized["stages"]["PLANNING"]["write_policy"]["writable_paths"] == [".agent/plan.yaml"]
    assert normalized["stages"]["PLANNING"]["artifacts_expected"] == [".agent/plan.yaml"]
    assert normalized["stages"]["PLANNING"]["artifacts_required"] == [{"path": ".agent/plan.yaml"}]
    assert normalized["stages"]["PLANNING"]["exit_conditions"]["any"] == []


def test_normalize_workflow_spec_preserves_rule_based_exit_conditions() -> None:
    """Test that exit rules are preserved in the internal shape."""
    spec = {
        "version": 2,
        "workflow": {"id": "command-exit", "title": "Command Exit", "entry": "VERIFY"},
        "globals": {"protected": [], "sensitive": [], "failures": {}, "finalize": {"require": []}, "session_start": {}},
        "stages": {
            "VERIFY": {
                "goal": "verify",
                "plan": "advance",
                "allow": {"write": [], "actions": [], "stop": False, "human": False},
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [
                    {
                        "rule": "command_succeeded",
                        "value": "(^|\\s)pytest(\\s|$)",
                        "display": "pytest must succeed during VERIFY",
                    }
                ],
                "expect": [],
                "next": [],
            }
        },
    }

    normalized = normalize_workflow_spec(spec)

    assert normalized["stages"]["VERIFY"]["exit_conditions"]["any"] == [
        {
            "rule": "command_succeeded",
            "value": "(^|\\s)pytest(\\s|$)",
            "display": "pytest must succeed during VERIFY",
        }
    ]


def test_invalid_command_rule_regex_fails_workflow_validation() -> None:
    """Test that command rule regexes are validated when loading the current DSL."""
    spec = {
        "version": 2,
        "workflow": {"id": "bad-command-regex", "title": "Bad", "entry": "VERIFY"},
        "globals": {"protected": [], "sensitive": [], "failures": {}, "finalize": {"require": []}, "session_start": {}},
        "stages": {
            "VERIFY": {
                "goal": "verify",
                "plan": "advance",
                "allow": {"write": [], "actions": [], "stop": False, "human": False},
                "deny": {"write": [], "actions": []},
                "enter": [],
                "exit": [{"rule": "command_succeeded", "value": "(", "display": "bad regex"}],
                "expect": [],
                "next": [],
            }
        },
    }

    try:
        validate_workflow_spec(normalize_workflow_spec(spec))
    except RuntimeError as exc:
        assert "command rule regex is invalid" in str(exc)
    else:
        raise AssertionError("Expected invalid command regex to fail validation")


def test_workflow_example_file_normalizes_and_validates() -> None:
    """Test that the checked-in workflow example stays parseable."""
    example_path = Path(__file__).resolve().parents[1] / "docs" / "workflow.example.yaml"
    payload = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    normalized = normalize_workflow_spec(payload)

    assert normalized["metadata"]["id"] == "standard-example"
    assert normalized["stages"]["REVIEW"]["artifacts_required"] == [{"path": ".agent/artifacts/review.md"}]
    assert normalized["stages"]["NEEDS_FAILURE_ANALYSIS"]["artifacts_required"] == [
        {
            "path": ".agent/artifacts/failure-analysis.md",
            "matches": "^## Failure Summary",
            "display": "failure-analysis.md must start with the Failure Summary section.",
        }
    ]


def test_discover_workflow_ids_prefers_user_workflow_directory(monkeypatch, tmp_path: Path) -> None:
    """Test that user-level workflow directories participate in discovery."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / "research.workflow.yaml").write_text("workflow: {}\nglobals: {}\nstages: {}\n", encoding="utf-8")
    monkeypatch.setattr("agent_guard.workflow_spec.user_workflow_dirs", lambda: [user_dir])

    workflow_ids = discover_workflow_ids()

    assert workflow_ids[0] == "default"
    assert "research" in workflow_ids


def test_checked_in_named_workflows_are_discoverable() -> None:
    """The repository should expose the checked-in named workflows for selection."""
    workflow_ids = discover_workflow_ids(Path(__file__).resolve().parents[1])

    assert workflow_ids[0] == "default"
    assert "research" in workflow_ids
    assert "docs" in workflow_ids


def test_load_workflow_spec_prefers_user_workflow_over_repo(monkeypatch, tmp_path: Path) -> None:
    """Test that user-level workflow files override repository-local workflow files."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    user_workflow = user_dir / "research.workflow.yaml"
    user_workflow.write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "workflow": {"id": "research-user", "title": "User Research", "entry": "QUESTION"},
                "globals": {"protected": [], "sensitive": [], "failures": {}, "finalize": {"require": []}, "session_start": {}},
                "stages": {
                    "QUESTION": {
                        "goal": "Start from user workflow.",
                        "plan": "deny",
                        "allow": {"write": [], "actions": [], "stop": True, "human": True},
                        "deny": {"write": [], "actions": []},
                        "enter": [],
                        "exit": [],
                        "expect": [],
                        "next": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (repo_dir / "workflows").mkdir()
    (repo_dir / "workflows" / "research.workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "workflow": {"id": "research-repo", "title": "Repo Research", "entry": "REPO"},
                "globals": {"protected": [], "sensitive": [], "failures": {}, "finalize": {"require": []}, "session_start": {}},
                "stages": {
                    "REPO": {
                        "goal": "Start from repo workflow.",
                        "plan": "deny",
                        "allow": {"write": [], "actions": [], "stop": True, "human": True},
                        "deny": {"write": [], "actions": []},
                        "enter": [],
                        "exit": [],
                        "expect": [],
                        "next": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_guard.workflow_spec.user_workflow_dirs", lambda: [user_dir])
    load_workflow_spec.cache_clear()

    spec = load_workflow_spec(repo_dir, "research")

    assert spec["metadata"]["id"] == "research-user"
    assert spec["entry_stage"] == "QUESTION"
    load_workflow_spec.cache_clear()


def test_checked_in_research_workflow_loads_and_resolves_roles() -> None:
    """The checked-in research workflow should be loadable through the named-workflow path."""
    spec = load_workflow_spec(workflow_id="research")

    assert spec["metadata"]["id"] == "research"
    assert spec["entry_stage"] == "QUESTIONING"
    assert wizard_defaults(workflow_id="research")["start_stages"] == ["QUESTIONING", "DISCOVER", "ANALYZE"]
    assert workflow_entry_stage(workflow_id="research") == "QUESTIONING"
    assert verification_stage(workflow_id="research") == "VALIDATE"
    assert failure_analysis_stage(workflow_id="research") == "NEEDS_FAILURE_ANALYSIS"
    assert completion_ready_stage(workflow_id="research") == "READY_TO_DELIVER"
    assert completion_stage(workflow_id="research") == "DONE"
    assert stage_write_policy("DISCOVER", workflow_id="research")["writable_paths"] == [
        "docs/**",
        "notes/**",
        "reports/**",
        ".agent/artifacts/research-brief.md",
    ]


def test_checked_in_docs_workflow_loads_and_resolves_roles() -> None:
    """The checked-in docs workflow should expose its own stage model and runtime roles."""
    spec = load_workflow_spec(workflow_id="docs")

    assert spec["metadata"]["id"] == "docs"
    assert spec["entry_stage"] == "INTAKE"
    assert wizard_defaults(workflow_id="docs")["start_stages"] == ["INTAKE", "OUTLINE", "DRAFT"]
    assert workflow_entry_stage(workflow_id="docs") == "INTAKE"
    assert verification_stage(workflow_id="docs") == "VALIDATE"
    assert failure_analysis_stage(workflow_id="docs") == "NEEDS_FAILURE_ANALYSIS"
    assert completion_ready_stage(workflow_id="docs") == "READY_TO_PUBLISH"
    assert completion_stage(workflow_id="docs") == "DONE"
    assert stage_write_policy("DRAFT", workflow_id="docs")["writable_paths"] == [
        "docs/**",
        "*.md",
        ".agent/artifacts/draft.md",
    ]


def test_load_workflow_spec_reports_friendly_message_for_invalid_yaml(monkeypatch, tmp_path: Path) -> None:
    """Test that invalid workflow YAML reports a repair-required message."""
    workflow_file = tmp_path / "default.workflow.yaml"
    workflow_file.write_text("workflow: [\n", encoding="utf-8")
    load_workflow_spec.cache_clear()
    monkeypatch.setattr("agent_guard.workflow_spec.packaged_workflow_path", lambda workflow_id=None: workflow_file)
    monkeypatch.setattr("agent_guard.workflow_spec.source_workflow_path", lambda workflow_id=None: workflow_file)

    try:
        load_workflow_spec()
    except RuntimeError as exc:
        assert "appears damaged" in str(exc)
        assert "cannot continue" in str(exc)
    else:
        raise AssertionError("Expected invalid workflow YAML to fail")
    finally:
        load_workflow_spec.cache_clear()


def test_load_workflow_spec_reports_friendly_message_for_non_mapping(monkeypatch, tmp_path: Path) -> None:
    """Test that non-mapping workflow documents report a repair-required message."""
    workflow_file = tmp_path / "default.workflow.yaml"
    workflow_file.write_text("- bad\n", encoding="utf-8")
    load_workflow_spec.cache_clear()
    monkeypatch.setattr("agent_guard.workflow_spec.packaged_workflow_path", lambda workflow_id=None: workflow_file)
    monkeypatch.setattr("agent_guard.workflow_spec.source_workflow_path", lambda workflow_id=None: workflow_file)

    try:
        load_workflow_spec()
    except RuntimeError as exc:
        assert "appears damaged" in str(exc)
        assert "cannot continue" in str(exc)
        assert "top-level document must be a YAML mapping" in str(exc)
    else:
        raise AssertionError("Expected non-mapping workflow YAML to fail")
    finally:
        load_workflow_spec.cache_clear()
