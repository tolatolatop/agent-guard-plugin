import json
import tempfile
from pathlib import Path

from agent_guard.install import build_opencode_plugin_source, install_runtime


def make_dirs() -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="agent-guard-install-"))
    home = Path(tempfile.mkdtemp(prefix="agent-guard-home-"))
    return root, home


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_install_writes_claude_code_project_settings_with_hook_commands() -> None:
    root, home = make_dirs()
    result = install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, PLUGIN_ROOT)

    config_path = root / ".claude" / "settings.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["runtime"] == "claude-code"
    assert len(config["hooks"]["PreToolUse"]) >= 1
    assert "agent-guard-bridge" in json.dumps(config)


def test_install_writes_codex_hooks_json() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "codex", "--scope", "project"], root, home, PLUGIN_ROOT)

    hooks_path = root / ".codex" / "hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))

    assert isinstance(hooks["hooks"]["SessionStart"], list)
    assert "pre-dispatch" in json.dumps(hooks)


def test_install_writes_opencode_loader() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "opencode", "--scope", "project"], root, home, PLUGIN_ROOT)

    plugin_path = root / ".opencode" / "plugins" / "agent-guard.js"
    source = plugin_path.read_text(encoding="utf-8")

    assert '"tool.execute.before"' in source
    assert "agent-guard-bridge" in source


def test_opencode_loader_stays_thin() -> None:
    source = build_opencode_plugin_source(PLUGIN_ROOT)
    assert "check-failure-loop" not in source
    assert "can-write" not in source
    assert "record-command" not in source
