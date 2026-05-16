"""Tests for agent-guard-fuse integration behavior."""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO

from agent_guard.application.use_cases import initialize_workspace, start_task
from agent_guard.cli import run_command
from agent_guard.fuse_integration import ensure_fuse_protection

from .helpers import make_temp_repo


def test_initialize_workspace_reports_fuse_state(monkeypatch) -> None:
    """Init should surface fuse integration status."""
    root_dir = make_temp_repo()
    monkeypatch.setattr(
        "agent_guard.application.use_cases.ensure_fuse_protection",
        lambda _: {"protection": "mounted", "enabled": True},
    )

    result = initialize_workspace(root_dir)

    assert result["fuse"]["protection"] == "mounted"


def test_start_task_reports_fuse_state(monkeypatch) -> None:
    """Start-task should surface fuse integration status."""
    root_dir = make_temp_repo()
    monkeypatch.setattr(
        "agent_guard.application.use_cases.ensure_fuse_protection",
        lambda _: {"protection": "mounted", "enabled": True},
    )

    result = start_task(root_dir, "password-reset")

    assert result["fuse"]["protection"] == "mounted"
    assert result["state"]["task_id"] == "password-reset"


def test_fuse_cli_commands_round_trip_status(monkeypatch) -> None:
    """CLI fuse commands should expose the integration helpers."""
    root_dir = make_temp_repo()
    monkeypatch.setattr(
        "agent_guard.cli.fuse_state",
        lambda _: {"protection": "inactive", "enabled": False},
    )
    monkeypatch.setattr(
        "agent_guard.cli.ensure_fuse_protection",
        lambda _: {"protection": "mounted", "enabled": True},
    )
    monkeypatch.setattr(
        "agent_guard.cli.stop_fuse_protection",
        lambda _: {"protection": "inactive", "enabled": False, "stopped": True},
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        try:
            run_command(["fuse-status"], root_dir)
        except SystemExit:
            pass
    payload = json.loads(stdout.getvalue())
    assert payload["fuse"]["protection"] == "inactive"

    stdout = StringIO()
    with redirect_stdout(stdout):
        try:
            run_command(["fuse-start"], root_dir)
        except SystemExit:
            pass
    payload = json.loads(stdout.getvalue())
    assert payload["fuse"]["protection"] == "mounted"

    stdout = StringIO()
    with redirect_stdout(stdout):
        try:
            run_command(["fuse-stop"], root_dir)
        except SystemExit:
            pass
    payload = json.loads(stdout.getvalue())
    assert payload["fuse"]["stopped"] is True


def test_ensure_fuse_protection_degrades_when_runtime_is_unavailable(monkeypatch) -> None:
    """Fuse integration should degrade cleanly when the runtime is unavailable."""
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard.fuse_integration.fuse_runtime_available", lambda: False)
    monkeypatch.setattr("agent_guard.fuse_integration.fuse_enabled", lambda _: False)

    result = ensure_fuse_protection(root_dir)

    assert result["protection"] == "unavailable"


def test_ensure_fuse_protection_starts_runtime_when_available(monkeypatch) -> None:
    """Fuse integration should start the runtime when it is available and inactive."""
    root_dir = make_temp_repo()
    enabled_states = iter([False, True])
    monkeypatch.setattr("agent_guard.fuse_integration.fuse_runtime_available", lambda: True)
    monkeypatch.setattr("agent_guard.fuse_integration.fuse_enabled", lambda _: next(enabled_states))
    monkeypatch.setattr(
        "agent_guard.fuse_integration.fuse_status",
        lambda _: {"running": False, "pid": None, "root": str(root_dir.resolve())},
    )
    monkeypatch.setattr("agent_guard.fuse_integration.start_fuse", lambda _: 43210)

    result = ensure_fuse_protection(root_dir)

    assert result["protection"] == "mounted"
    assert result["started"] is True
    assert result["pid"] == 43210
