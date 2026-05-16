"""Tests for test install."""
import json
from io import StringIO
import tempfile
from pathlib import Path
import tomllib
import pytest

from agent_guard.install import (
    build_opencode_plugin_source,
    install_claude_skills_bundle,
    install_runtime,
    packaged_skills_dir,
    parse_flags,
    selected_skill_sources,
    selected_skill_sources_with_fallback,
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


def test_wheel_force_include_maps_docs_skills_directory() -> None:
    """Test that wheel packaging includes the full docs/skills directory."""
    pyproject = tomllib.loads((PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert force_include["docs/skills"] == "agent_guard/_bundled_skills"
    assert "docs/skills/using-workflow.md" not in force_include


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


def test_parse_flags_supports_short_interactive_alias() -> None:
    """Test that parse flags supports the short interactive alias."""
    flags = parse_flags(["-i"])

    assert flags["interactive"] is True


def test_parse_flags_accumulates_repeated_match_flags() -> None:
    """Test that repeated skill selection flags accumulate."""
    flags = parse_flags(["--match", "workflow", "--match", "final", "--exclude-match", "failure"])

    assert flags["match"] == ["workflow", "final"]
    assert flags["exclude-match"] == ["failure"]


def test_selected_skill_sources_support_positive_match_selection() -> None:
    """Test that positive match selection keeps only matching skills."""
    selected = selected_skill_sources(PLUGIN_ROOT, include_matches=["finalization|workflow-core"])

    assert [path.stem for path in selected] == ["finalization-checklist", "workflow-core"]


def test_selected_skill_sources_support_negative_match_selection() -> None:
    """Test that negative match selection excludes matching skills."""
    selected = selected_skill_sources(PLUGIN_ROOT, exclude_matches=["failure|finalization"])

    assert "failure-analysis" not in {path.stem for path in selected}
    assert "finalization-checklist" not in {path.stem for path in selected}
    assert "using-workflow" in {path.stem for path in selected}


def test_install_runtime_supports_selective_skill_installation() -> None:
    """Test that install_runtime can install only a selected subset of skills."""
    root, home = make_dirs()
    result = install_runtime(
        ["--runtime", "claude-code", "--scope", "project", "--match", "workflow-core|using-workflow", "--exclude-match", "using-workflow"],
        root,
        home,
        PLUGIN_ROOT,
    )

    assert (root / ".claude" / "skills" / "workflow-core" / "SKILL.md").exists()
    assert not (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()
    assert any(path.endswith("/workflow-core/SKILL.md") for path in result["files_written"])


def test_install_runtime_fails_when_skill_filters_select_nothing() -> None:
    """Test that install_runtime fails closed when filters select no skills."""
    root, home = make_dirs()

    with pytest.raises(RuntimeError, match="No Claude workflow skills were installed"):
        install_runtime(
            ["--runtime", "claude-code", "--scope", "project", "--match", "definitely-no-such-skill"],
            root,
            home,
            PLUGIN_ROOT,
        )


def test_selected_skill_sources_with_workflow_defaults_fall_back_to_full_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that empty workflow-driven selection only warns and falls back to full install."""
    monkeypatch.setattr(
        "agent_guard.install.workflow_install_defaults",
        lambda: {"skill_match": ["definitely-no-such-skill"], "skill_exclude_match": []},
    )

    selected, warnings = selected_skill_sources_with_fallback(PLUGIN_ROOT)

    assert "using-workflow" in {path.stem for path in selected}
    assert warnings == [
        "Workflow skill selection matched no installable skills; ignoring match=['definitely-no-such-skill'] from workflow defaults and falling back to full install."
    ]


def test_install_runtime_uses_workflow_defaults_when_cli_filters_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that workflow install defaults apply when install is called without explicit filters."""
    monkeypatch.setattr(
        "agent_guard.install.workflow_install_defaults",
        lambda: {"skill_match": ["workflow-core"], "skill_exclude_match": []},
    )
    root, home = make_dirs()

    result = install_runtime(["--runtime", "claude-code", "--scope", "project"], root, home, PLUGIN_ROOT)

    assert (root / ".claude" / "skills" / "workflow-core" / "SKILL.md").exists()
    assert not (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()
    assert result["notes"][0] == "Installed Claude Code hooks into a settings JSON file."


def test_install_runtime_supports_interactive_prompts() -> None:
    """Test that install_runtime can collect options interactively."""
    root, home = make_dirs()
    answers = StringIO("codex\nproject\n\n\nn\n")

    result = install_runtime(
        ["--interactive"],
        root,
        home,
        PLUGIN_ROOT,
        input_stream=answers,
        output=StringIO(),
    )

    assert result["runtime"] == "codex"
    assert result["scope"] == "project"
    assert (root / ".codex" / "hooks.json").exists()
    assert (root / ".agent-guard" / "skills" / "workflow-core.md").exists()


def test_install_runtime_prompts_for_missing_runtime_and_scope() -> None:
    """Test that install prompts for runtime and scope when omitted."""
    root, home = make_dirs()
    answers = StringIO("codex\nproject\nn\n")

    result = install_runtime(
        [],
        root,
        home,
        PLUGIN_ROOT,
        input_stream=answers,
        output=StringIO(),
    )

    assert result["runtime"] == "codex"
    assert result["scope"] == "project"
    assert (root / ".codex" / "hooks.json").exists()


def test_install_runtime_prompts_only_for_missing_scope() -> None:
    """Test that install prompts only for the missing install axis."""
    root, home = make_dirs()
    answers = StringIO("user\nn\n")

    result = install_runtime(
        ["--runtime", "codex"],
        root,
        home,
        PLUGIN_ROOT,
        input_stream=answers,
        output=StringIO(),
    )

    assert result["runtime"] == "codex"
    assert result["scope"] == "user"
    assert (home / ".codex" / "hooks.json").exists()


def test_install_runtime_supports_short_interactive_alias() -> None:
    """Test that install_runtime can collect options through -i."""
    root, home = make_dirs()
    answers = StringIO("codex\nproject\n\n\nn\n")

    result = install_runtime(
        ["-i"],
        root,
        home,
        PLUGIN_ROOT,
        input_stream=answers,
        output=StringIO(),
    )

    assert result["runtime"] == "codex"
    assert (root / ".codex" / "hooks.json").exists()


def test_install_runtime_interactive_filters_override_workflow_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that interactive filter input overrides workflow-default skill filters."""
    monkeypatch.setattr(
        "agent_guard.install.workflow_install_defaults",
        lambda: {"skill_match": ["definitely-no-such-skill"], "skill_exclude_match": []},
    )
    root, home = make_dirs()
    answers = StringIO("claude-code\nproject\nworkflow-core\n\nn\n")

    result = install_runtime(
        ["--interactive"],
        root,
        home,
        PLUGIN_ROOT,
        input_stream=answers,
        output=StringIO(),
    )

    assert result["runtime"] == "claude-code"
    assert (root / ".claude" / "skills" / "workflow-core" / "SKILL.md").exists()
    assert not (root / ".claude" / "skills" / "using-workflow" / "SKILL.md").exists()


def test_install_runtime_can_enter_wizard_after_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that install can chain into the setup wizard when requested."""
    root, home = make_dirs()
    monkeypatch.setattr(
        "agent_guard.wizard.run_wizard",
        lambda cwd, input_stream, output: {"ok": True, "task_id": "demo-task", "state": {"stage": "CLARIFYING"}},
    )

    result = install_runtime(["--runtime", "codex", "--scope", "project", "--wizard"], root, home, PLUGIN_ROOT)

    assert result["runtime"] == "codex"
    assert result["wizard"] == {"ok": True, "task_id": "demo-task", "state": {"stage": "CLARIFYING"}}


def test_install_runtime_interactive_can_enable_wizard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that interactive install can opt into the wizard flow."""
    root, home = make_dirs()
    answers = StringIO("codex\nproject\n\n\ny\n")
    monkeypatch.setattr(
        "agent_guard.wizard.run_wizard",
        lambda cwd, input_stream, output: {"ok": True, "task_id": "wizard-task"},
    )

    result = install_runtime(
        ["--interactive"],
        root,
        home,
        PLUGIN_ROOT,
        input_stream=answers,
        output=StringIO(),
    )

    assert result["wizard"] == {"ok": True, "task_id": "wizard-task"}


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
