"""Tests for runtime integration registration and event normalization."""
from pathlib import Path

import pytest

from agent_guard.install import install_runtime
from agent_guard.runtime_integrations import SUPPORTED_RUNTIMES, get_runtime_integration
from agent_guard.runtime_integrations.opencode import normalize_after_event, normalize_before_event

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_registry_exposes_each_supported_runtime() -> None:
    """Every advertised runtime resolves to a matching integration."""
    assert SUPPORTED_RUNTIMES == ("claude-code", "codex", "opencode")
    assert [get_runtime_integration(name).name for name in SUPPORTED_RUNTIMES] == list(SUPPORTED_RUNTIMES)


def test_registry_rejects_unknown_runtime() -> None:
    """Registry lookup fails with the supported runtime list."""
    with pytest.raises(RuntimeError, match="claude-code, codex, opencode"):
        get_runtime_integration("unknown")


def test_opencode_before_normalizes_apply_patch_paths() -> None:
    """OpenCode apply_patch events become one generic write action per path."""
    actions = normalize_before_event(
        {
            "input": {"tool": "apply_patch"},
            "output": {
                "args": {
                    "patchText": "*** Begin Patch\n*** Update File: src/a.py\n*** Add File: src/b.py\n*** End Patch"
                }
            },
        }
    )

    assert [action.action for action in actions] == ["pre-write", "pre-write"]
    assert [action.payload["tool_input"]["file_path"] for action in actions] == ["src/a.py", "src/b.py"]
    assert {action.source for action in actions} == {"opencode-before"}


def test_opencode_after_normalizes_bash_result() -> None:
    """OpenCode bash output becomes the bridge's generic post-command shape."""
    actions = normalize_after_event(
        {
            "input": {"tool": "bash"},
            "output": {
                "args": {"command": "pytest -q"},
                "result": {"stdout": "ok", "exitCode": 0},
            },
        }
    )

    assert len(actions) == 1
    assert actions[0].action == "post-command"
    assert actions[0].payload == {
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"stdout": "ok", "exitCode": 0},
    }


@pytest.mark.parametrize("runtime", SUPPORTED_RUNTIMES)
def test_hook_only_uninstall_plans_preserve_skills(tmp_path: Path, runtime: str) -> None:
    """The registry can plan hook removal without path-string filtering."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    install_runtime(["--runtime", runtime, "--scope", "project"], root, home, PLUGIN_ROOT)

    plan = get_runtime_integration(runtime).plan_uninstall(
        root, home, "project", include_skills=False
    )

    assert plan["changes"]
    assert {change["component"] for change in plan["changes"]} == {"hooks"}
    assert any(path.name == "SKILL.md" for path in root.rglob("SKILL.md"))
