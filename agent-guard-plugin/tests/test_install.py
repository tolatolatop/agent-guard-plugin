import json
from io import StringIO
import tempfile
from pathlib import Path

from agent_guard.install import build_opencode_plugin_source, install_runtime, uninstall_runtime


def make_dirs() -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="agent-guard-install-"))
    home = Path(tempfile.mkdtemp(prefix="agent-guard-home-"))
    return root, home


def assert_dir_empty(path: Path) -> None:
    assert path.exists()
    assert list(path.iterdir()) == []


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_install_writes_claude_code_project_settings_with_hook_commands() -> None:
    root, home = make_dirs()
    result = install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, PLUGIN_ROOT)

    config_path = root / ".claude" / "settings.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["runtime"] == "claude-code"
    assert len(config["hooks"]["PreToolUse"]) >= 1
    assert "agent-guard-bridge" in json.dumps(config)
    assert "AGENT_GUARD_SKILLS_DIR" in json.dumps(config)
    assert config["hooks"]["SessionStart"][0]["matcher"] == "startup|clear|compact"
    assert config["hooks"]["SessionStart"][0]["hooks"][0]["async"] is False
    assert (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()
    assert (root / ".claude" / "skills" / "workflow-core" / "SKILL.md").exists()
    assert_dir_empty(home)


def test_install_claude_removes_legacy_flat_skill_files() -> None:
    root, home = make_dirs()
    legacy_file = root / ".claude" / "skills" / "using-workflow.md"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("legacy\n", encoding="utf-8")

    install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, PLUGIN_ROOT)

    assert not legacy_file.exists()
    assert (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()


def test_install_writes_codex_hooks_json() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "codex", "--scope", "project"], root, home, PLUGIN_ROOT)

    hooks_path = root / ".codex" / "hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))

    assert isinstance(hooks["hooks"]["SessionStart"], list)
    assert "pre-dispatch" in json.dumps(hooks)
    assert "AGENT_GUARD_SKILLS_DIR" in json.dumps(hooks)
    assert (root / ".agent-guard" / "skills" / "workflow-core.md").exists()
    assert_dir_empty(home)


def test_install_writes_opencode_loader() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "opencode", "--scope", "project"], root, home, PLUGIN_ROOT)

    plugin_path = root / ".opencode" / "plugins" / "agent-guard.js"
    source = plugin_path.read_text(encoding="utf-8")

    assert '"tool.execute.before"' in source
    assert "agent-guard-bridge" in source
    assert "AGENT_GUARD_SKILLS_DIR" in source
    assert (root / ".opencode" / "skills" / "finalization-checklist" / "SKILL.md").exists()
    assert_dir_empty(home)


def test_install_opencode_removes_legacy_flat_skill_files() -> None:
    root, home = make_dirs()
    legacy_file = root / ".opencode" / "skills" / "using-workflow.md"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("legacy\n", encoding="utf-8")

    install_runtime(["--runtime", "opencode", "--scope", "project"], root, home, PLUGIN_ROOT)

    assert not legacy_file.exists()
    assert (root / ".opencode" / "skills" / "using-workflow" / "SKILL.md").exists()


def test_opencode_loader_stays_thin() -> None:
    source = build_opencode_plugin_source(PLUGIN_ROOT, PLUGIN_ROOT / ".agent-guard" / "skills")
    assert "check-failure-loop" not in source
    assert "can-write" not in source
    assert "record-command" not in source


def test_uninstall_codex_lists_and_removes_hooks_after_confirmation() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "codex", "--scope", "project"], root, home, PLUGIN_ROOT)

    output = StringIO()
    result = uninstall_runtime(
        ["--runtime", "codex", "--scope", "project"],
        root,
        home,
        output=output,
        input_stream=StringIO("y\n"),
    )

    assert result["cancelled"] is False
    assert not (root / ".codex" / "hooks.json").exists()
    assert not (root / ".agent-guard" / "skills").exists()
    rendered = output.getvalue()
    assert "The following changes will be applied" in rendered
    assert ".codex/hooks.json" in rendered


def test_uninstall_can_be_cancelled() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "opencode", "--scope", "project"], root, home, PLUGIN_ROOT)

    result = uninstall_runtime(
        ["--runtime", "opencode", "--scope", "project"],
        root,
        home,
        output=StringIO(),
        input_stream=StringIO("n\n"),
    )

    assert result["cancelled"] is True
    assert (root / ".opencode" / "plugins" / "agent-guard.js").exists()
    assert (root / ".opencode" / "skills" / "using-workflow" / "SKILL.md").exists()


def test_uninstall_claude_removes_skills_bundle_after_confirmation() -> None:
    root, home = make_dirs()
    install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, PLUGIN_ROOT)

    result = uninstall_runtime(
        ["--runtime", "claude-code", "--scope", "project"],
        root,
        home,
        output=StringIO(),
        input_stream=StringIO("y\n"),
    )

    assert result["cancelled"] is False
    assert not (root / ".claude" / "skills").exists()
