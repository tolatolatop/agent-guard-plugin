from agent_guard.jobs import load_jobs
from agent_guard.state import DEFAULT_JOBS, DEFAULT_STATE, ensure_agent_files, load_state, save_state

from .helpers import make_temp_repo


def test_state_defaults_to_idle_when_agent_dir_is_missing() -> None:
    root_dir = make_temp_repo()
    for child in (root_dir / ".agent").rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted((root_dir / ".agent").rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    (root_dir / ".agent").rmdir()

    assert load_state(root_dir) == DEFAULT_STATE
    assert load_jobs(root_dir) == DEFAULT_JOBS


def test_state_loads_defaults_after_init() -> None:
    root_dir = make_temp_repo()
    assert load_state(root_dir) == DEFAULT_STATE


def test_init_creates_agent_artifacts_directory() -> None:
    root_dir = make_temp_repo()
    agent_dir = root_dir / ".agent"
    artifacts_dir = agent_dir / "artifacts"

    assert agent_dir.exists()
    assert artifacts_dir.exists()
    assert artifacts_dir.is_dir()

    extra_root = root_dir / "fresh-init"
    extra_root.mkdir()
    ensure_agent_files(extra_root)
    assert (extra_root / ".agent" / "artifacts").is_dir()


def test_state_saves_and_reloads_updates() -> None:
    root_dir = make_temp_repo()
    next_state = {**DEFAULT_STATE, "stage": "RED_TEST", "current_step": "red-001"}
    save_state(root_dir, next_state)
    assert load_state(root_dir) == next_state
