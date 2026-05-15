"""Tests for test path policy."""
from agent_guard.path_policy import decide_write
from agent_guard.state import DEFAULT_STATE


def test_idle_blocks_project_writes_until_task_started() -> None:
    """Test that idle blocks project writes until task started."""
    result = decide_write(DEFAULT_STATE, "pyproject.toml")
    assert result["decision"] == "block"
    assert "Run agent-guard start-task" in result["reason"]


def test_clarifying_blocks_direct_project_file_edits() -> None:
    """Test that clarifying blocks direct project file edits."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "CLARIFYING"},
        "pyproject.toml",
    )
    assert result["decision"] == "block"
    assert "not writable during CLARIFYING" in result["reason"]


def test_red_test_blocks_src_writes() -> None:
    """Test that red test blocks src writes."""
    result = decide_write({**DEFAULT_STATE, "task_id": "password-reset", "stage": "RED_TEST"}, "src/auth/reset.py")
    assert result["decision"] == "block"


def test_red_test_allows_test_writes_in_allowed_scope() -> None:
    """Test that red test allows test writes in allowed scope."""
    result = decide_write({**DEFAULT_STATE, "task_id": "password-reset", "stage": "RED_TEST"}, "tests/auth/test_password_reset.py")
    assert result["decision"] == "allow"


def test_sensitive_paths_require_approval() -> None:
    """Test that sensitive paths require approval."""
    result = decide_write({**DEFAULT_STATE, "task_id": "password-reset", "stage": "GREEN_IMPL"}, ".github/workflows/ci.yml")
    assert result["decision"] == "block"


def test_state_json_cannot_be_modified_directly() -> None:
    """Test that state json cannot be modified directly."""
    result = decide_write({**DEFAULT_STATE, "task_id": "password-reset", "stage": "GREEN_IMPL"}, ".agent/state.json")
    assert result["decision"] == "block"
    assert "managed by agent-guard" in result["reason"]


def test_planning_allows_agent_plan_updates_only() -> None:
    """Test that planning allows agent plan updates only."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "PLANNING"},
        ".agent/plan.yaml",
    )
    assert result["decision"] == "allow"


def test_clarifying_blocks_agent_plan_updates_when_plan_mode_is_not_create() -> None:
    """Test that non-create plan modes automatically block plan.yaml writes."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "CLARIFYING"},
        ".agent/plan.yaml",
    )
    assert result["decision"] == "block"


def test_planning_blocks_root_plan_markdown() -> None:
    """Test that planning blocks root plan markdown outside the managed artifact path."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "PLANNING"},
        "./PLAN.md",
    )
    assert result["decision"] == "block"


def test_designing_blocks_root_design_markdown() -> None:
    """Test that designing blocks root design markdown outside the managed artifact path."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "DESIGNING"},
        "./DESIGN.md",
    )
    assert result["decision"] == "block"


def test_planning_allows_absolute_agent_artifact_paths() -> None:
    """Test that planning allows absolute agent artifact paths."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "PLANNING"},
        "/tmp/test-guard/.agent/plan.yaml",
    )
    assert result["decision"] == "allow"


def test_ready_to_summarize_allows_summary_artifact_only() -> None:
    """Test that ready to summarize allows summary artifact only."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "READY_TO_SUMMARIZE"},
        ".agent/artifacts/summary.md",
    )
    assert result["decision"] == "allow"

    blocked_result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "READY_TO_SUMMARIZE"},
        "src/app.py",
    )
    assert blocked_result["decision"] == "block"
