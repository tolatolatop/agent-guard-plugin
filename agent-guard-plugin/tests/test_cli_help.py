"""Tests for CLI help output."""
from contextlib import redirect_stdout
from io import StringIO

from agent_guard.cli import run_command

from .helpers import make_temp_repo


def invoke_help(argv: list[str]) -> tuple[int, str]:
    """Invoke CLI and capture plain-text stdout."""
    root_dir = make_temp_repo()
    stdout = StringIO()
    code = 0
    with redirect_stdout(stdout):
        try:
            run_command(argv, root_dir)
        except SystemExit as exc:
            code = int(exc.code)
    return code, stdout.getvalue()


def test_top_level_help_flag_prints_command_overview() -> None:
    """Test that top-level help flag prints command overview."""
    code, output = invoke_help(["--help"])

    assert code == 0
    assert "Usage: agent-guard <command> [options]" in output
    assert "close-task [--force]" in output
    assert "record-command --cmd CMD --exit-code CODE [--log PATH]" in output
    assert "verify [--auto-ready] -- CMD ..." in output
    assert "version" in output
    assert "help [command]" in output


def test_subcommand_help_flag_prints_specific_usage() -> None:
    """Test that subcommand help flag prints specific usage."""
    code, output = invoke_help(["record-command", "--help"])

    assert code == 0
    assert "Usage: agent-guard record-command --cmd CMD --exit-code CODE [--log PATH]" in output
    assert "Record command execution details" in output


def test_verify_help_prints_specific_usage() -> None:
    """Test that verify help documents the convenience command."""
    code, output = invoke_help(["verify", "--help"])

    assert code == 0
    assert "Usage: agent-guard verify [--auto-ready] -- CMD ..." in output
    assert "last_verification" in output


def test_install_help_mentions_workflow_context_defaults() -> None:
    """Test that install help documents workflow-aware skill defaults."""
    code, output = invoke_help(["install", "--help"])

    assert code == 0
    assert "--workflow ID" in output
    assert "bound workflow" in output


def test_help_command_supports_command_specific_help() -> None:
    """Test that help command supports command-specific help."""
    code, output = invoke_help(["help", "close-task"])

    assert code == 0
    assert "Usage: agent-guard close-task [--force]" in output
    assert "release .agent protection" in output


def test_version_command_prints_package_version() -> None:
    """Test that version command prints a human-readable version."""
    code, output = invoke_help(["version"])

    assert code == 0
    assert output == "agent-guard 0.3.1\n"


def test_global_version_flag_prints_package_version() -> None:
    """Test that --version prints the same version string."""
    code, output = invoke_help(["--version"])

    assert code == 0
    assert output == "agent-guard 0.3.1\n"


def test_missing_command_prints_help_and_exits_nonzero() -> None:
    """Test that missing command prints help and exits nonzero."""
    code, output = invoke_help([])

    assert code == 1
    assert "Usage: agent-guard <command> [options]" in output


def test_json_command_output_is_single_line() -> None:
    """Test that JSON CLI output stays shell-friendly on one line."""
    code, output = invoke_help(["init"])

    assert code == 0
    assert len(output.splitlines()) == 1
