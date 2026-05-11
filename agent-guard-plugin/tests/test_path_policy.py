from agent_guard.path_policy import decide_write
from agent_guard.state import DEFAULT_STATE


def test_red_test_blocks_src_writes() -> None:
    result = decide_write(
        {**DEFAULT_STATE, "stage": "RED_TEST", "allowed_paths": ["tests/**"], "forbidden_paths": ["src/**"]},
        "src/auth/reset.py",
    )
    assert result["decision"] == "block"


def test_red_test_allows_test_writes_in_allowed_scope() -> None:
    result = decide_write(
        {**DEFAULT_STATE, "stage": "RED_TEST", "allowed_paths": ["tests/**"], "forbidden_paths": ["src/**"]},
        "tests/auth/test_password_reset.py",
    )
    assert result["decision"] == "allow"


def test_sensitive_paths_require_approval() -> None:
    result = decide_write(
        {**DEFAULT_STATE, "stage": "GREEN_IMPL", "allowed_paths": [".github/**"], "forbidden_paths": []},
        ".github/workflows/ci.yml",
    )
    assert result["decision"] == "block"
