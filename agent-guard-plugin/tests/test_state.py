from agent_guard.state import DEFAULT_STATE, load_state, save_state

from .helpers import make_temp_repo


def test_state_loads_defaults_after_init() -> None:
    root_dir = make_temp_repo()
    assert load_state(root_dir) == DEFAULT_STATE


def test_state_saves_and_reloads_updates() -> None:
    root_dir = make_temp_repo()
    next_state = {**DEFAULT_STATE, "stage": "RED_TEST", "current_step": "red-001"}
    save_state(root_dir, next_state)
    assert load_state(root_dir) == next_state
