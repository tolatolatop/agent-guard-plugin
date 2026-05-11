from __future__ import annotations

from pathlib import Path
from typing import TextIO

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.shortcuts import confirm


def _is_tty(stream: TextIO) -> bool:
    checker = getattr(stream, "isatty", None)
    return bool(checker and checker())


def use_prompt_toolkit(input_stream: TextIO, output: TextIO) -> bool:
    return _is_tty(input_stream) and _is_tty(output)


def confirm_action(message: str, input_stream: TextIO, output: TextIO) -> bool:
    if use_prompt_toolkit(input_stream, output):
        return bool(confirm(message=message))

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
    if use_prompt_toolkit(input_stream, output):
        return prompt(f"{message}: ", default=default).strip()

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
    if use_prompt_toolkit(input_stream, output):
        completer = WordCompleter(choices, ignore_case=True, sentence=True)
        while True:
            answer = prompt(f"{message}: ", default=default, completer=completer).strip() or default
            if answer in choices:
                return answer

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
    if use_prompt_toolkit(input_stream, output):
        return prompt(f"{message}: ", default=default, completer=PathCompleter(expanduser=True)).strip()

    return prompt_text(message, input_stream, output, default=default)
