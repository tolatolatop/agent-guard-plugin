"""Tests for test interactive."""
from io import StringIO

from agent_guard.interactive import confirm_action, prompt_text, use_prompt_toolkit


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
