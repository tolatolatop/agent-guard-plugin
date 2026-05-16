"""Tests for test interactive."""
from io import StringIO

import pytest

from agent_guard.interactive import confirm_action, prompt_choice, prompt_text, use_prompt_toolkit


def test_use_prompt_toolkit_is_disabled_for_string_streams() -> None:
    """Test that use prompt toolkit is disabled for string streams."""
    assert use_prompt_toolkit(StringIO(), StringIO()) is False


def test_confirm_action_falls_back_to_plain_streams() -> None:
    """Test that confirm action falls back to plain streams."""
    output = StringIO()
    confirmed = confirm_action("Proceed with uninstall?", StringIO("y\n"), output)

    assert confirmed is True
    assert "Proceed with uninstall?" in output.getvalue()


def test_prompt_text_falls_back_to_plain_streams() -> None:
    """Test that prompt text falls back to plain streams."""
    output = StringIO()
    result = prompt_text("Task name", StringIO("\n"), output, default="demo-task")

    assert result == "demo-task"
    assert "Task name" in output.getvalue()


def test_prompt_choice_uses_inquirerpy_select_for_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that prompt choices use InquirerPy select in tty mode."""

    class FakePrompt:
        def execute(self) -> str:
            return "codex"

    monkeypatch.setattr("agent_guard.interactive.use_prompt_toolkit", lambda *_: True)
    monkeypatch.setattr("agent_guard.interactive.inquirer.select", lambda **_: FakePrompt())

    result = prompt_choice("Runtime", ["claude-code", "codex", "opencode"], StringIO(), StringIO(), default="codex")

    assert result == "codex"


def test_prompt_text_uses_inquirerpy_text_for_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that prompt text uses InquirerPy text in tty mode."""

    class FakePrompt:
        def execute(self) -> str:
            return "demo-task"

    monkeypatch.setattr("agent_guard.interactive.use_prompt_toolkit", lambda *_: True)
    monkeypatch.setattr("agent_guard.interactive.inquirer.text", lambda **_: FakePrompt())

    result = prompt_text("Task id", StringIO(), StringIO(), default="demo")

    assert result == "demo-task"


def test_confirm_action_uses_inquirerpy_confirm_for_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that confirm action uses InquirerPy confirm in tty mode."""

    class FakePrompt:
        def execute(self) -> bool:
            return True

    monkeypatch.setattr("agent_guard.interactive.use_prompt_toolkit", lambda *_: True)
    monkeypatch.setattr("agent_guard.interactive.inquirer.confirm", lambda **_: FakePrompt())

    confirmed = confirm_action("Proceed?", StringIO(), StringIO())

    assert confirmed is True
