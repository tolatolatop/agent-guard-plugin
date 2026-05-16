"""Interactive terminal prompts used by setup and uninstall flows."""
from __future__ import annotations

from typing import TextIO

try:
    from InquirerPy import inquirer
except ImportError:  # pragma: no cover - optional at runtime
    class _MissingInquirer:
        """Placeholder object so tests can monkeypatch prompt methods."""

        def select(self, **_: object) -> object:
            raise RuntimeError("InquirerPy is not installed.")

        def text(self, **_: object) -> object:
            raise RuntimeError("InquirerPy is not installed.")

        def confirm(self, **_: object) -> object:
            raise RuntimeError("InquirerPy is not installed.")

        def filepath(self, **_: object) -> object:
            raise RuntimeError("InquirerPy is not installed.")

    inquirer = _MissingInquirer()


def _is_tty(stream: TextIO) -> bool:
    """Internal helper for is tty."""
    checker = getattr(stream, "isatty", None)
    return bool(checker and checker())


def use_prompt_toolkit(input_stream: TextIO, output: TextIO) -> bool:
    """Use prompt toolkit."""
    return type(inquirer).__name__ != "_MissingInquirer" and _is_tty(input_stream) and _is_tty(output)


def confirm_action(message: str, input_stream: TextIO, output: TextIO) -> bool:
    """Confirm action."""
    if use_prompt_toolkit(input_stream, output):
        return bool(inquirer.confirm(message=message, default=False).execute())

    output.write(f"{message} [y/N]: ")
    output.flush()
    answer = input_stream.readline().strip().lower()
    return answer in {"y", "yes"}


def prompt_text(
    message: str,
    input_stream: TextIO,
    output: TextIO,
    default: str = "",
) -> str:
    """Prompt for text."""
    if use_prompt_toolkit(input_stream, output):
        answer = inquirer.text(message=message, default=default).execute()
        return str(answer).strip()

    suffix = f" [{default}]" if default else ""
    output.write(f"{message}{suffix}: ")
    output.flush()
    answer = input_stream.readline().strip()
    return answer or default


def prompt_choice(
    message: str,
    choices: list[str],
    input_stream: TextIO,
    output: TextIO,
    default: str,
) -> str:
    """Prompt for choice."""
    if use_prompt_toolkit(input_stream, output):
        answer = inquirer.select(message=message, choices=choices, default=default).execute()
        if answer in choices:
            return str(answer)

    options = "/".join(choices)
    while True:
        output.write(f"{message} [{options}] ({default}): ")
        output.flush()
        answer = input_stream.readline().strip() or default
        if answer in choices:
            return answer


def prompt_path(
    message: str,
    input_stream: TextIO,
    output: TextIO,
    default: str = "",
) -> str:
    """Prompt for path."""
    if use_prompt_toolkit(input_stream, output):
        answer = inquirer.filepath(message=message, default=default).execute()
        return str(answer).strip()

    return prompt_text(message, input_stream, output, default=default)
