"""Tests for helpers."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent_guard.state import DEFAULT_STATE, ensure_agent_files, save_state


def make_temp_repo() -> Path:
    """Helper for make temp repo."""
    root_dir = Path(tempfile.mkdtemp(prefix="agent-guard-"))
    ensure_agent_files(root_dir)
    return root_dir


def write_state(root_dir: Path, **override: object) -> dict[str, object]:
    """Helper for write state."""
    state = {**DEFAULT_STATE, **override}
    state.pop("allowed_paths", None)
    state.pop("forbidden_paths", None)
    save_state(root_dir, state)
    return state
