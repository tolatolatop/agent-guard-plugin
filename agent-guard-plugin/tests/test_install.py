"""Tests for test install."""
import json
from io import StringIO
import tempfile
from pathlib import Path
import pytest

from agent_guard.install import (
    build_opencode_plugin_source,
    install_claude_skills_bundle,
    install_runtime,
    packaged_skills_dir,
    parse_flags,
    source_skills_dir,
    uninstall_runtime,
)


def make_dirs() -> tuple[Path, Path]:
    """Helper for make dirs."""
    root = Path(tempfile.mkdtemp(prefix="agent-guard-install-"))
    home = Path(tempfile.mkdtemp(prefix="agent-guard-home-"))
    return root, home


def assert_dir_empty(path: Path) -> None:
    """Helper for assert dir empty."""
    assert path.exists()
    assert list(path.iterdir()) == []


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_install_writes_claude_code_project_settings_with_hook_commands() -> None:
    """Test that install writes claude code project settings with hook commands."""
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
    """Test that install claude removes legacy flat skill files."""
    root, home = make_dirs()
    legacy_file = root / ".claude" / "skills" / "using-workflow.md"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("legacy\n", encoding="utf-8")

    install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, PLUGIN_ROOT)

    assert not legacy_file.exists()
    assert (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()


def test_source_skills_dir_prefers_packaged_bundle_when_plugin_root_has_no_docs() -> None:
    """Test that source skills dir falls back to packaged resolver when plugin root has no docs."""
    root, _ = make_dirs()

    resolved = source_skills_dir(root)

    assert resolved == packaged_skills_dir()
    assert (resolved / "using-workflow.md").exists()


def test_source_skills_dir_prefers_repo_docs_when_available() -> None:
    """Test that source skills dir prefers repo docs when available."""
    resolved = source_skills_dir(PLUGIN_ROOT)

    assert resolved == PLUGIN_ROOT / "docs" / "skills"
    assert (resolved / "using-workflow.md").exists()


def test_packaged_skills_dir_falls_back_to_repo_docs_when_bundle_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that packaged skills dir falls back to repo docs when bundled skills are absent."""
    fake_repo_root = tmp_path / "plugin-root"
    fake_package_dir = fake_repo_root / "src" / "agent_guard"
    fake_package_dir.mkdir(parents=True)
    docs_dir = fake_repo_root / "docs" / "skills"
    docs_dir.mkdir(parents=True)
    (docs_dir / "using-workflow.md").write_text("# skill\n", encoding="utf-8")
    monkeypatch.setattr("agent_guard.install.__file__", str(fake_package_dir / "install.py"))

    resolved = packaged_skills_dir()

    assert resolved == docs_dir
    assert (resolved / "using-workflow.md").exists()


def test_install_claude_skills_bundle_succeeds_without_plugin_docs() -> None:
    """Test that install claude skills bundle succeeds without plugin docs."""
    root, home = make_dirs()
    fake_plugin_root = root / "installed-layout"
    fake_plugin_root.mkdir(parents=True, exist_ok=True)

    result = install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, fake_plugin_root)

    assert (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()
    assert any(path.endswith("/.claude/skills/using-workflow/SKILL.md") for path in result["files_written"])


def test_install_claude_skills_bundle_errors_when_no_sources_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that install claude skills bundle errors when no sources exist."""
    empty_dir = tmp_path / "empty-skills"
    empty_dir.mkdir()
    monkeypatch.setattr("agent_guard.install.packaged_skills_dir", lambda: empty_dir)

    with pytest.raises(RuntimeError, match="Could not locate bundled workflow skills"):
        install_claude_skills_bundle(tmp_path / "target", tmp_path / "plugin-root")


def test_parse_flags_supports_short_runtime_and_scope_aliases() -> None:
    """Test that parse flags supports short runtime and scope aliases."""
    flags = parse_flags(["-r", "claude-code", "-s", "project"])

    assert flags["runtime"] == "claude-code"
    assert flags["scope"] == "project"


def test_install_writes_codex_hooks_json() -> None:
    """Test that install writes codex hooks json."""
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
    """Test that install writes opencode loader."""
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
    """Test that install opencode removes legacy flat skill files."""
    root, home = make_dirs()
    legacy_file = root / ".opencode" / "skills" / "using-workflow.md"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("legacy\n", encoding="utf-8")

    install_runtime(["--runtime", "opencode", "--scope", "project"], root, home, PLUGIN_ROOT)

    assert not legacy_file.exists()
    assert (root / ".opencode" / "skills" / "using-workflow" / "SKILL.md").exists()


def test_opencode_loader_stays_thin() -> None:
    """Test that opencode loader stays thin."""
    source = build_opencode_plugin_source(PLUGIN_ROOT, PLUGIN_ROOT / ".agent-guard" / "skills")
    assert "check-failure-loop" not in source
    assert "can-write" not in source
    assert "record-command" not in source


def test_uninstall_codex_lists_and_removes_hooks_after_confirmation() -> None:
    """Test that uninstall codex lists and removes hooks after confirmation."""
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
    """Test that uninstall can be cancelled."""
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
    """Test that uninstall claude removes skills bundle after confirmation."""
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
