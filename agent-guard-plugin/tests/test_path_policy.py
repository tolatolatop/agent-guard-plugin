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
    assert "Direct project file edits are not allowed" in result["reason"]


def test_red_test_blocks_src_writes() -> None:
    """Test that red test blocks src writes."""
    result = decide_write(
        {**DEFAULT_STATE, "stage": "RED_TEST", "allowed_paths": ["tests/**"], "forbidden_paths": ["src/**"]},
        "src/auth/reset.py",
    )
    assert result["decision"] == "block"


def test_red_test_allows_test_writes_in_allowed_scope() -> None:
    """Test that red test allows test writes in allowed scope."""
    result = decide_write(
        {**DEFAULT_STATE, "stage": "RED_TEST", "allowed_paths": ["tests/**"], "forbidden_paths": ["src/**"]},
        "tests/auth/test_password_reset.py",
    )
    assert result["decision"] == "allow"


def test_sensitive_paths_require_approval() -> None:
    """Test that sensitive paths require approval."""
    result = decide_write(
        {**DEFAULT_STATE, "stage": "GREEN_IMPL", "allowed_paths": [".github/**"], "forbidden_paths": []},
        ".github/workflows/ci.yml",
    )
    assert result["decision"] == "block"


def test_state_json_cannot_be_modified_directly() -> None:
    """Test that state json cannot be modified directly."""
    result = decide_write(
        {**DEFAULT_STATE, "stage": "GREEN_IMPL", "allowed_paths": [".agent/**"], "forbidden_paths": []},
        ".agent/state.json",
    )
    assert result["decision"] == "block"
    assert "managed by agent-guard" in result["reason"]


def test_planning_allows_agent_plan_updates_only() -> None:
    """Test that planning allows agent plan updates only."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "PLANNING"},
        ".agent/plan.yaml",
    )
    assert result["decision"] == "allow"


def test_planning_allows_root_plan_markdown() -> None:
    """Test that planning allows root plan markdown."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "PLANNING"},
        "./PLAN.md",
    )
    assert result["decision"] == "allow"


def test_designing_allows_root_design_markdown() -> None:
    """Test that designing allows root design markdown."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "DESIGNING"},
        "./DESIGN.md",
    )
    assert result["decision"] == "allow"


def test_planning_allows_absolute_agent_artifact_paths() -> None:
    """Test that planning allows absolute agent artifact paths."""
    result = decide_write(
        {**DEFAULT_STATE, "task_id": "init-video-clipper", "stage": "PLANNING"},
        "/tmp/test-guard/.agent/artifacts/DESIGN.md",
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
