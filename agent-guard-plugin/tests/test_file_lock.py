"""Tests for the minimal file-lock SDK."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_guard.infrastructure.repositories import PlanRepository, StateRepository
from agent_guard.state import DEFAULT_STATE, current_managed_state_dir, load_state, save_state
from agent_guard_file_lock import (
    AGENT_DIR,
    DEFAULT_PLAN_RELATIVE,
    DEFAULT_STATE_RELATIVE,
    delete,
    derive_state_id,
    fuse_enabled,
    fuse_status,
    load_locks,
    lock,
    lock_file,
    lock_file_path,
    managed_file_path,
    pid_file,
    public_file_path,
    save_locks,
    start_fuse,
    stop_fuse,
    unlock,
    unlock_file,
    write,
)

from .helpers import make_temp_repo


def test_derive_state_id_is_stable_for_workspace() -> None:
    root_dir = make_temp_repo()

    first = derive_state_id(root_dir)
    second = derive_state_id(root_dir)

    assert first == second
    assert len(first) == 32


def test_lock_creates_global_lock_json_entry() -> None:
    root_dir = make_temp_repo()
    root_key = str(root_dir.resolve())

    token = lock(root_dir)
    payload = load_locks()

    assert payload["version"] == 3
    assert payload["roots"][root_key]["managed"] == str(
        managed_file_path(root_dir, DEFAULT_PLAN_RELATIVE).parent.resolve()
    )
    assert payload["roots"][root_key]["files"] == []
    assert payload["roots"][root_key]["token"] == token
    assert lock_file_path().exists()


def test_lock_reuses_workspace_token() -> None:
    root_dir = make_temp_repo()
    first = lock(root_dir)
    lock_file(str(public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)), first)
    second = lock(root_dir)
    payload = load_locks()

    assert first == second
    assert payload["roots"][str(root_dir.resolve())]["token"] == first
    assert payload["roots"][str(root_dir.resolve())]["files"] == ["plan.yaml"]


def test_lock_file_and_unlock_file_update_locked_file_set() -> None:
    root_dir = make_temp_repo()
    root_key = str(root_dir.resolve())
    token = lock(root_dir)
    plan_path = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    state_path = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)

    assert lock_file(str(plan_path), token) is True
    assert load_locks()["roots"][root_key]["files"] == ["plan.yaml"]

    assert lock_file(str(state_path), token) is True
    assert load_locks()["roots"][root_key]["files"] == ["plan.yaml", "state.json"]

    assert unlock_file(str(plan_path), token) is True
    assert load_locks()["roots"][root_key]["files"] == ["state.json"]


def test_lock_file_and_unlock_file_fail_with_wrong_token() -> None:
    root_dir = make_temp_repo()
    token = lock(root_dir)
    plan_path = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)

    with pytest.raises(PermissionError):
        lock_file(str(plan_path), "wrong-token")

    lock_file(str(plan_path), token)
    with pytest.raises(PermissionError):
        unlock_file(str(plan_path), "wrong-token")

    assert load_locks()["roots"][str(root_dir.resolve())]["files"] == ["plan.yaml"]


def test_unlock_only_succeeds_with_matching_token_and_clears_files() -> None:
    root_dir = make_temp_repo()
    root_key = str(root_dir.resolve())
    token = lock(root_dir)
    plan_path = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    lock_file(str(plan_path), token)

    assert unlock(root_dir, "wrong-token") is False
    assert unlock(root_dir, token) is True
    assert load_locks()["roots"][root_key]["token"] == ""
    assert load_locks()["roots"][root_key]["files"] == []


def test_write_requires_matching_file_lock_and_writes_public_path() -> None:
    root_dir = make_temp_repo()
    target = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)
    token = lock(root_dir)

    with pytest.raises(PermissionError):
        write(str(target), "{}\n", token)

    lock_file(str(target), token)
    write(str(target), '{"task_id": null}\n', token)

    assert target.read_text(encoding="utf-8") == '{"task_id": null}\n'
    assert load_locks()["roots"][str(root_dir.resolve())]["files"] == ["state.json"]


def test_write_and_delete_restore_locked_files_after_operation() -> None:
    root_dir = make_temp_repo()
    state_target = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)
    plan_target = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    plan_target.write_text("task_id: demo\nsteps: []\n", encoding="utf-8")
    token = lock(root_dir)

    lock_file(str(state_target), token)
    lock_file(str(plan_target), token)
    write(str(state_target), '{"task_id":"demo"}\n', token)
    assert set(load_locks()["roots"][str(root_dir.resolve())]["files"]) == {
        "state.json",
        "plan.yaml",
    }

    delete(str(plan_target), token)
    assert set(load_locks()["roots"][str(root_dir.resolve())]["files"]) == {
        "state.json",
        "plan.yaml",
    }


def test_delete_requires_matching_file_lock() -> None:
    root_dir = make_temp_repo()
    target = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    target.write_text("task_id: demo\nsteps: []\n", encoding="utf-8")
    token = lock(root_dir)

    with pytest.raises(PermissionError):
        delete(str(target), token)

    lock_file(str(target), token)
    assert delete(str(target), token) is True
    assert not target.exists()


def test_delete_requires_matching_root_token_when_file_is_locked() -> None:
    root_dir = make_temp_repo()
    target = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    target.write_text("task_id: demo\nsteps: []\n", encoding="utf-8")
    token = lock(root_dir)
    lock_file(str(target), token)

    with pytest.raises(PermissionError):
        delete(str(target), "wrong-token")


def test_save_state_uses_managed_storage_when_fuse_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard.state.fuse_enabled", lambda _: False)
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_enabled", lambda _: False)

    saved = save_state(
        root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "VERIFY"}
    )

    assert saved["state_id"] == derive_state_id(root_dir)
    assert managed_file_path(root_dir, DEFAULT_STATE_RELATIVE).read_text(encoding="utf-8")
    assert public_file_path(root_dir, DEFAULT_STATE_RELATIVE).read_text(encoding="utf-8")


def test_plan_repository_mirrors_public_and_managed_when_fuse_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard.infrastructure.repositories.fuse_enabled", lambda _: False)

    repository = PlanRepository(root_dir)
    repository.save_steps("password-reset", [])

    managed_text = managed_file_path(root_dir, DEFAULT_PLAN_RELATIVE).read_text(
        encoding="utf-8"
    )
    public_text = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE).read_text(
        encoding="utf-8"
    )
    assert managed_text == public_text == "task_id: password-reset\nsteps: []\n"


def test_load_state_backfills_stable_state_id_from_workspace() -> None:
    root_dir = make_temp_repo()
    (root_dir / AGENT_DIR / "state.json").write_text(
        '{"task_id": "password-reset", "workflow_id": null, "stage": "VERIFY", "current_step": null, "can_finalize": false, "last_verification": null, "needs_human": false}\n',
        encoding="utf-8",
    )

    state = load_state(root_dir)

    assert state["state_id"] == derive_state_id(root_dir)
    assert current_managed_state_dir(root_dir) == Path.home() / ".agent-guard-fuse" / "managed" / state["state_id"]


def test_fuse_enabled_requires_agent_dir_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    agent_dir = root_dir / AGENT_DIR
    agent_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "is_mount", lambda self: self == agent_dir)

    assert fuse_enabled(root_dir) is True


def test_state_repository_round_trips_task_session() -> None:
    root_dir = make_temp_repo()
    save_state(
        root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "VERIFY"}
    )

    loaded = StateRepository(root_dir).load()

    assert loaded.task_id == "password-reset"
    assert loaded.state_id == derive_state_id(root_dir)


def test_save_locks_persists_expected_wire_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "lock.json"
    monkeypatch.setattr("agent_guard_file_lock.core.LOCK_FILE", lock_path)
    monkeypatch.setattr("agent_guard_file_lock.core.LOCK_ROOT", tmp_path)

    save_locks(
        {
            "version": 3,
            "roots": {
                "/repo": {
                    "managed": "/managed/repo",
                    "token": "token-a",
                    "files": ["plan.yaml"],
                }
            },
        }
    )

    assert json.loads(lock_path.read_text(encoding="utf-8")) == {
        "version": 3,
        "roots": {
            "/repo": {
                "managed": "/managed/repo",
                "token": "token-a",
                "files": ["plan.yaml"],
            }
        },
    }


def test_start_fuse_records_detached_runtime_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = make_temp_repo()
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs.LOCK_ROOT", runtime_root)
    monkeypatch.setattr(
        "agent_guard_file_lock.fuse_fs.mount_command",
        lambda root: ["agent-guard-fuse", "mount", "--root", str(root)],
    )
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs._wait_for_mount", lambda root, timeout_seconds=5.0: True)

    class FakeProcess:
        pid = 43210

        def poll(self) -> None:
            return None

    popen_calls: list[dict[str, object]] = []

    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProcess:
        popen_calls.append({"cmd": cmd, **kwargs})
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs._process_alive", lambda pid: True)

    pid = start_fuse(root_dir)

    assert pid == 43210
    assert popen_calls[0]["start_new_session"] is True
    assert popen_calls[0]["stdin"] is not None
    assert pid_file(root_dir).exists()
    assert fuse_status(root_dir)["running"] is True


def test_start_fuse_rejects_duplicate_running_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = make_temp_repo()
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs.LOCK_ROOT", runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    pid_file(root_dir).parent.mkdir(parents=True, exist_ok=True)
    pid_file(root_dir).write_text(
        json.dumps({"pid": 12345, "root": str(root_dir.resolve())}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs._process_alive", lambda pid: True)

    with pytest.raises(RuntimeError, match="already running"):
        start_fuse(root_dir)


def test_fuse_status_cleans_stale_pid_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = make_temp_repo()
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs.LOCK_ROOT", runtime_root)
    pid_file(root_dir).parent.mkdir(parents=True, exist_ok=True)
    pid_file(root_dir).write_text(
        json.dumps({"pid": 12345, "root": str(root_dir.resolve())}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs._process_alive", lambda pid: False)

    status = fuse_status(root_dir)

    assert status["running"] is False
    assert not pid_file(root_dir).exists()


def test_stop_fuse_unmounts_and_cleans_pid_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = make_temp_repo()
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr("agent_guard_file_lock.fuse_fs.LOCK_ROOT", runtime_root)
    pid_file(root_dir).parent.mkdir(parents=True, exist_ok=True)
    pid_file(root_dir).write_text(
        json.dumps({"pid": 54321, "root": str(root_dir.resolve())}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_guard_file_lock.fuse_fs.unmount_command",
        lambda root: ["agent-guard-fuse", "unmount", "--root", str(root)],
    )
    run_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object):
        run_calls.append(cmd)

        class Result:
            returncode = 0

        return Result()

    alive_states = iter([True, False])
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "agent_guard_file_lock.fuse_fs._process_alive", lambda pid: next(alive_states)
    )

    assert stop_fuse(root_dir) is True
    assert run_calls == [["agent-guard-fuse", "unmount", "--root", str(root_dir)]]
    assert not pid_file(root_dir).exists()
