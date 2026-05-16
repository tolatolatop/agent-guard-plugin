from __future__ import annotations

"""
BDD scenarios covered by this integration module:

1. Given `.agent/` is missing, empty, or already contains files, when the real
   Rust FUSE runtime mounts the workspace, then `.agent/` itself becomes the
   mountpoint and the runtime prepares a root lock record if one does not
   already exist.

2. Given this is the first mount for one workspace, when mount succeeds, then
   the runtime creates a root lock entry with `files=[]` and does not pre-lock
   any managed file.

3. Given the root already exists in `lock.json`, when the workspace is mounted
   again, then mount does not reset `token` or `files`; it only performs sync
   and reattaches the FUSE view.

4. Given `.agent/state.json` or `.agent/plan.yaml` exists in both `.agent/`
   and managed-state before mount, when one side has the newer modification
   time, then mount synchronizes the newer content into the older side before
   taking over `.agent/`.

5. Given `.agent/` already contains legacy managed files and passthrough
   content before mount, when managed-state already has a conflicting managed
   file, then mount preserves the newer synchronized managed-state view while
   keeping passthrough content available through `.agent.backing/`.

6. Given passthrough files and directories already exist under `.agent/` before
   mount, when mount takes over `.agent/`, then those entries are preserved
   through `.agent.backing/` and remain accessible through the mounted `.agent/`
   view.

7. Given a workspace mounted by the real Rust FUSE runtime, when the Python SDK
   acquires a root token, locks `plan.yaml`, writes through the SDK, and then
   unlocks the file again, then the managed backing file is updated and direct
   writes to `.agent/plan.yaml` are rejected only while that file remains in the
   current locked-file set.

8. Given both `state.json` and `plan.yaml` exist under the mounted `.agent/`,
   when only one of them is added to the current locked-file set, then direct
   writes to that file are denied while the other managed file still behaves as
   an ordinary mounted file.

9. Given a managed file is currently locked, when SDK `write(...)` or
   `delete(...)` is used with the correct token, then the operation succeeds and
   the file remains in the current locked-file set afterward.

10. Given multiple managed files are currently locked for one workspace, when
    `unlock(root, token)` is called, then all file-level locks are cleared and
    direct writes on those files return to ordinary mounted-file behavior.

11. Given both `state.json` and `plan.yaml` are currently locked, when SDK
    `write(...)` is called for each file with the same root token, then both
    writes succeed and each managed backing file is updated independently.

12. Given `.agent/` is mounted and only `plan.yaml` is currently locked, when
    unprotected files and directories such as `events.jsonl` and `artifacts/`
    are created, written, or deleted, then they behave like normal filesystem
    entries without requiring any token.

13. Given managed content changed while mounted, when the runtime unmounts,
    then the latest managed content is synchronized back into the visible
    `.agent/` directory using the same mtime-priority rule.
"""

import os
from pathlib import Path
import subprocess
import time

import pytest

from agent_guard_file_lock import (
    DEFAULT_PLAN_RELATIVE,
    DEFAULT_STATE_RELATIVE,
    delete,
    derive_state_id,
    load_locks,
    lock,
    lock_file,
    public_file_path,
    unlock,
    unlock_file,
    write,
)


def _runtime_binary() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_dir = repo_root / "fuse-runtime"
    subprocess.run(["cargo", "build", "-q"], cwd=runtime_dir, check=True)
    return runtime_dir / "target" / "debug" / "agent-guard-fuse"


def _managed_root(temp_home: Path, root_dir: Path) -> Path:
    return temp_home / ".agent-guard" / "state" / derive_state_id(root_dir)


def _managed_file(temp_home: Path, root_dir: Path, relative_path: str) -> Path:
    return _managed_root(temp_home, root_dir) / Path(relative_path).name


def _seed_managed_files(temp_home: Path, root_dir: Path) -> None:
    managed_root = _managed_root(temp_home, root_dir)
    managed_root.mkdir(parents=True, exist_ok=True)
    (managed_root / "state.json").write_text(
        '{"task_id": null, "stage": "IDLE"}\n', encoding="utf-8"
    )
    (managed_root / "plan.yaml").write_text("task_id: null\nsteps: []\n", encoding="utf-8")


def _patch_managed_paths(monkeypatch: pytest.MonkeyPatch, temp_home: Path) -> None:
    import agent_guard.state as state_module
    import agent_guard.infrastructure.repositories as repositories_module
    import agent_guard_file_lock.core as lock_core

    def managed_file(root_dir: Path, relative_path: str) -> Path:
        return _managed_file(temp_home, root_dir, relative_path)

    monkeypatch.setattr(lock_core, "LOCK_ROOT", temp_home / ".agent-guard-fuse")
    monkeypatch.setattr(lock_core, "LOCK_FILE", temp_home / ".agent-guard-fuse" / "lock.json")
    monkeypatch.setattr(
        lock_core, "_managed_root_for", lambda root_dir: str(_managed_root(temp_home, Path(root_dir)))
    )
    monkeypatch.setattr(lock_core, "managed_file_path", managed_file)
    monkeypatch.setattr(state_module, "managed_file_path", managed_file)
    monkeypatch.setattr(repositories_module, "managed_file_path", managed_file)
    monkeypatch.setattr(state_module, "managed_state_root", lambda: temp_home / ".agent-guard" / "state")
    monkeypatch.setattr(
        state_module,
        "managed_state_dir",
        lambda state_id: temp_home / ".agent-guard" / "state" / state_id,
    )


def _wait_for_mount(root_dir: Path, proc: subprocess.Popen[str]) -> None:
    deadline = time.time() + 5
    mount_dir = root_dir / ".agent"
    while time.time() < deadline:
        if mount_dir.exists() and mount_dir.is_mount():
            return
        time.sleep(0.1)
    proc.terminate()
    raise AssertionError("fuse mount did not become ready")


@pytest.fixture
def mounted_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root_dir = tmp_path / "repo"
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_home = tmp_path / "home"
    temp_home.mkdir(parents=True, exist_ok=True)
    _patch_managed_paths(monkeypatch, temp_home)
    _seed_managed_files(temp_home, root_dir)

    runtime = _runtime_binary()
    env = {**os.environ, "HOME": str(temp_home)}
    proc = subprocess.Popen([str(runtime), "mount", "--root", str(root_dir)], env=env)
    _wait_for_mount(root_dir, proc)

    try:
        yield root_dir, temp_home, env
    finally:
        subprocess.run([str(runtime), "unmount", "--root", str(root_dir)], env=env, check=True)
        proc.wait(timeout=5)


def _mount_root(root_dir: Path, temp_home: Path) -> tuple[Path, dict[str, str], subprocess.Popen[str]]:
    runtime = _runtime_binary()
    env = {**os.environ, "HOME": str(temp_home)}
    proc = subprocess.Popen([str(runtime), "mount", "--root", str(root_dir)], env=env)
    _wait_for_mount(root_dir, proc)
    return runtime, env, proc


@pytest.mark.parametrize("agent_layout", ["missing", "empty", "non_empty"])
def test_mount_creation_handles_missing_empty_and_non_empty_agent_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_layout: str
) -> None:
    root_dir = tmp_path / f"repo-{agent_layout}"
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_home = tmp_path / f"home-{agent_layout}"
    temp_home.mkdir(parents=True, exist_ok=True)
    _patch_managed_paths(monkeypatch, temp_home)
    _seed_managed_files(temp_home, root_dir)

    agent_dir = root_dir / ".agent"
    if agent_layout == "empty":
        agent_dir.mkdir(parents=True, exist_ok=True)
    elif agent_layout == "non_empty":
        agent_dir.mkdir(parents=True, exist_ok=True)
        _managed_file(temp_home, root_dir, DEFAULT_STATE_RELATIVE).unlink(missing_ok=True)
        (agent_dir / "state.json").write_text(
            '{"task_id":"legacy","stage":"PLANNING"}\n', encoding="utf-8"
        )
        (agent_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (agent_dir / "events.jsonl").write_text('{"event":"legacy"}\n', encoding="utf-8")

    runtime, env, proc = _mount_root(root_dir, temp_home)
    try:
        assert agent_dir.is_mount()
        assert public_file_path(root_dir, DEFAULT_STATE_RELATIVE).exists()
        assert public_file_path(root_dir, DEFAULT_PLAN_RELATIVE).exists()

        if agent_layout == "non_empty":
            assert _managed_file(temp_home, root_dir, DEFAULT_STATE_RELATIVE).read_text(
                encoding="utf-8"
            ) == '{"task_id":"legacy","stage":"PLANNING"}\n'
            assert (root_dir / ".agent" / "artifacts").is_dir()
            assert (root_dir / ".agent" / "events.jsonl").read_text(encoding="utf-8") == '{"event":"legacy"}\n'
            assert (root_dir / ".agent.backing" / "artifacts").is_dir()
            assert (root_dir / ".agent.backing" / "events.jsonl").read_text(encoding="utf-8") == '{"event":"legacy"}\n'
    finally:
        subprocess.run([str(runtime), "unmount", "--root", str(root_dir)], env=env, check=True)
        proc.wait(timeout=5)


def test_first_mount_creates_root_lock_entry_with_empty_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = tmp_path / "repo-first-mount"
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_home = tmp_path / "home-first-mount"
    temp_home.mkdir(parents=True, exist_ok=True)
    _patch_managed_paths(monkeypatch, temp_home)
    _seed_managed_files(temp_home, root_dir)

    runtime, env, proc = _mount_root(root_dir, temp_home)
    try:
        payload = load_locks()
        assert payload["roots"][str(root_dir.resolve())]["files"] == []
        assert payload["roots"][str(root_dir.resolve())]["token"] == ""
    finally:
        subprocess.run([str(runtime), "unmount", "--root", str(root_dir)], env=env, check=True)
        proc.wait(timeout=5)


def test_mount_sync_prefers_newer_workspace_managed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = tmp_path / "repo-sync-forward"
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_home = tmp_path / "home-sync-forward"
    temp_home.mkdir(parents=True, exist_ok=True)
    _patch_managed_paths(monkeypatch, temp_home)
    _seed_managed_files(temp_home, root_dir)

    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    public_plan.parent.mkdir(parents=True, exist_ok=True)
    public_plan.write_text("task_id: newer-workspace\nsteps: []\n", encoding="utf-8")
    time.sleep(0.02)
    public_plan.touch()

    runtime, env, proc = _mount_root(root_dir, temp_home)
    try:
        assert _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE).read_text(
            encoding="utf-8"
        ) == "task_id: newer-workspace\nsteps: []\n"
        assert public_plan.read_text(encoding="utf-8") == "task_id: newer-workspace\nsteps: []\n"
    finally:
        subprocess.run([str(runtime), "unmount", "--root", str(root_dir)], env=env, check=True)
        proc.wait(timeout=5)


def test_unmount_sync_restores_latest_managed_content_into_visible_agent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = tmp_path / "repo-sync-back"
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_home = tmp_path / "home-sync-back"
    temp_home.mkdir(parents=True, exist_ok=True)
    _patch_managed_paths(monkeypatch, temp_home)
    _seed_managed_files(temp_home, root_dir)

    runtime, env, proc = _mount_root(root_dir, temp_home)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)
    managed_plan.write_text("task_id: latest-managed\nsteps: []\n", encoding="utf-8")
    time.sleep(0.02)
    managed_plan.touch()
    subprocess.run([str(runtime), "unmount", "--root", str(root_dir)], env=env, check=True)
    proc.wait(timeout=5)

    assert public_file_path(root_dir, DEFAULT_PLAN_RELATIVE).read_text(
        encoding="utf-8"
    ) == "task_id: latest-managed\nsteps: []\n"


def test_mount_creation_preserves_existing_managed_file_over_stale_workspace_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_dir = tmp_path / "repo-conflict"
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_home = tmp_path / "home-conflict"
    temp_home.mkdir(parents=True, exist_ok=True)
    _patch_managed_paths(monkeypatch, temp_home)
    _seed_managed_files(temp_home, root_dir)

    agent_dir = root_dir / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "plan.yaml").write_text("task_id: stale\nsteps: []\n", encoding="utf-8")
    (agent_dir / "events.jsonl").write_text('{"event":"legacy"}\n', encoding="utf-8")

    runtime, env, proc = _mount_root(root_dir, temp_home)
    try:
        assert public_file_path(root_dir, DEFAULT_PLAN_RELATIVE).read_text(
            encoding="utf-8"
        ) == "task_id: null\nsteps: []\n"
        assert _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE).read_text(
            encoding="utf-8"
        ) == "task_id: null\nsteps: []\n"
        assert (root_dir / ".agent" / "events.jsonl").read_text(encoding="utf-8") == '{"event":"legacy"}\n'
    finally:
        subprocess.run([str(runtime), "unmount", "--root", str(root_dir)], env=env, check=True)
        proc.wait(timeout=5)


def test_sdk_file_lock_controls_plan_write_over_real_fuse_mount(mounted_workspace) -> None:
    root_dir, temp_home, _env = mounted_workspace
    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)

    public_plan.write_text("task_id: direct-before-lock\nsteps: []\n", encoding="utf-8")
    assert managed_plan.read_text(encoding="utf-8") == "task_id: direct-before-lock\nsteps: []\n"

    token = lock(root_dir)
    lock_file(str(public_plan), token)
    try:
        with pytest.raises(PermissionError):
            public_plan.write_text("task_id: denied-while-locked\nsteps: []\n", encoding="utf-8")

        write(str(public_plan), "task_id: sdk-write\nsteps: []\n", token)
        assert managed_plan.read_text(encoding="utf-8") == "task_id: sdk-write\nsteps: []\n"
    finally:
        assert unlock_file(str(public_plan), token) is True
        assert unlock(root_dir, token) is True

    public_plan.write_text("task_id: direct-after-unlock\nsteps: []\n", encoding="utf-8")
    assert managed_plan.read_text(encoding="utf-8") == "task_id: direct-after-unlock\nsteps: []\n"


def test_managed_files_can_be_locked_independently_over_real_fuse_mount(
    mounted_workspace,
) -> None:
    root_dir, temp_home, _env = mounted_workspace
    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    public_state = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)
    managed_state = _managed_file(temp_home, root_dir, DEFAULT_STATE_RELATIVE)
    token = lock(root_dir)

    lock_file(str(public_plan), token)
    try:
        with pytest.raises(PermissionError):
            public_plan.write_text("task_id: denied\nsteps: []\n", encoding="utf-8")

        public_state.write_text('{"task_id":"allowed","stage":"VERIFY"}\n', encoding="utf-8")
        assert managed_state.read_text(encoding="utf-8") == '{"task_id":"allowed","stage":"VERIFY"}\n'
        assert managed_plan.read_text(encoding="utf-8") == "task_id: null\nsteps: []\n"
    finally:
        unlock_file(str(public_plan), token)
        unlock(root_dir, token)


def test_sdk_write_and_delete_preserve_locked_file_membership(
    mounted_workspace,
) -> None:
    root_dir, temp_home, _env = mounted_workspace
    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    public_state = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)
    token = lock(root_dir)

    lock_file(str(public_plan), token)
    lock_file(str(public_state), token)
    write(str(public_plan), "task_id: via-sdk\nsteps: []\n", token)
    assert managed_plan.read_text(encoding="utf-8") == "task_id: via-sdk\nsteps: []\n"
    assert set(load_locks()["roots"][str(root_dir.resolve())]["files"]) == {
        "plan.yaml",
        "state.json",
    }

    assert delete(str(public_plan), token) is True
    assert set(load_locks()["roots"][str(root_dir.resolve())]["files"]) == {
        "plan.yaml",
        "state.json",
    }

    unlock_file(str(public_plan), token)
    unlock_file(str(public_state), token)
    unlock(root_dir, token)


def test_unlock_root_clears_multiple_locked_files_and_restores_direct_writes(
    mounted_workspace,
) -> None:
    root_dir, temp_home, _env = mounted_workspace
    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    public_state = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)
    managed_state = _managed_file(temp_home, root_dir, DEFAULT_STATE_RELATIVE)
    token = lock(root_dir)

    lock_file(str(public_plan), token)
    lock_file(str(public_state), token)
    with pytest.raises(PermissionError):
        public_plan.write_text("task_id: denied\nsteps: []\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        public_state.write_text('{"task_id":"denied","stage":"REVIEW"}\n', encoding="utf-8")

    assert unlock(root_dir, token) is True
    assert load_locks()["roots"][str(root_dir.resolve())]["files"] == []

    public_plan.write_text("task_id: unlocked-root\nsteps: []\n", encoding="utf-8")
    public_state.write_text('{"task_id":"unlocked-root","stage":"VERIFY"}\n', encoding="utf-8")

    assert managed_plan.read_text(encoding="utf-8") == "task_id: unlocked-root\nsteps: []\n"
    assert managed_state.read_text(encoding="utf-8") == '{"task_id":"unlocked-root","stage":"VERIFY"}\n'


def test_sdk_can_write_both_locked_managed_files_with_one_root_token(
    mounted_workspace,
) -> None:
    root_dir, temp_home, _env = mounted_workspace
    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    public_state = public_file_path(root_dir, DEFAULT_STATE_RELATIVE)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)
    managed_state = _managed_file(temp_home, root_dir, DEFAULT_STATE_RELATIVE)
    token = lock(root_dir)

    lock_file(str(public_plan), token)
    lock_file(str(public_state), token)
    try:
        write(str(public_plan), "task_id: plan-sdk\nsteps: []\n", token)
        write(str(public_state), '{"task_id":"state-sdk","stage":"GREEN_IMPL"}\n', token)
    finally:
        unlock_file(str(public_plan), token)
        unlock_file(str(public_state), token)
        unlock(root_dir, token)

    assert managed_plan.read_text(encoding="utf-8") == "task_id: plan-sdk\nsteps: []\n"
    assert managed_state.read_text(encoding="utf-8") == '{"task_id":"state-sdk","stage":"GREEN_IMPL"}\n'


def test_unprotected_files_and_directories_passthrough_while_locked_file_needs_token(
    mounted_workspace,
) -> None:
    root_dir, temp_home, _env = mounted_workspace
    artifacts_dir = root_dir / ".agent" / "artifacts"
    events_file = root_dir / ".agent" / "events.jsonl"
    public_plan = public_file_path(root_dir, DEFAULT_PLAN_RELATIVE)
    managed_plan = _managed_file(temp_home, root_dir, DEFAULT_PLAN_RELATIVE)
    managed_plan.parent.mkdir(parents=True, exist_ok=True)
    managed_plan.write_text("task_id: demo\nsteps: []\n", encoding="utf-8")

    token = lock(root_dir)
    lock_file(str(public_plan), token)
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        events_file.write_text('{"event":"ok"}\n', encoding="utf-8")

        assert artifacts_dir.is_dir()
        assert events_file.read_text(encoding="utf-8") == '{"event":"ok"}\n'
        assert (root_dir / ".agent.backing" / "events.jsonl").read_text(encoding="utf-8") == '{"event":"ok"}\n'
        assert events_file.unlink() is None
        assert not events_file.exists()
        assert not (root_dir / ".agent.backing" / "events.jsonl").exists()

        with pytest.raises(PermissionError):
            public_plan.unlink()

        assert delete(str(public_plan), token) is True
        assert not managed_plan.exists()
    finally:
        unlock_file(str(public_plan), token)
        unlock(root_dir, token)
