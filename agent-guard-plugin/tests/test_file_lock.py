"""Tests for token-gated FUSE file locks."""
from __future__ import annotations

from pathlib import Path
import json
import pytest

from agent_guard_file_lock import (
    delete_protected_file,
    grant_file_lock,
    load_manifest,
    lock_status,
    protect_file,
    read_protected_text,
    resolve_protected_path,
    revoke_file_lock,
    write_protected_text,
)
from agent_guard.infrastructure.repositories import PlanRepository, StateRepository
from agent_guard.state import DEFAULT_STATE, current_managed_state_dir, load_state, save_state

from .helpers import make_temp_repo


def test_protect_file_moves_original_to_managed_state_and_replaces_public_path_with_mount_symlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_dir = make_temp_repo()
    state_file = root_dir / ".agent" / "state.json"
    original = state_file.read_text(encoding="utf-8")
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)

    result = protect_file(root_dir, ".agent/state.json", "secret-token")

    managed_path = Path(result["managed_path"])
    assert result["mode"] == "fuse"
    assert state_file.is_symlink()
    assert managed_path.parent == current_managed_state_dir(root_dir)
    assert '"stage": "IDLE"' in original
    assert '"stage": "IDLE"' in managed_path.read_text(encoding="utf-8")
    assert read_protected_text(root_dir, ".agent/state.json") == managed_path.read_text(encoding="utf-8")
    assert load_state(root_dir)["fuse"] == "enabled"
    assert (current_managed_state_dir(root_dir) / "file-lock.json").exists()


def test_write_protected_text_requires_matching_token_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)
    protect_file(root_dir, ".agent/state.json", "secret-token", token_env="STATE_WRITE_TOKEN")

    with pytest.raises(PermissionError):
        write_protected_text(root_dir, ".agent/state.json", "{}\n")

    write_protected_text(
        root_dir,
        ".agent/state.json",
        '{"task_id": null, "workflow_id": null, "stage": "IDLE", "current_step": null, "can_finalize": false, "last_verification": null, "needs_human": false, "state_id": "abc", "fuse": "enabled"}\n',
        env={"STATE_WRITE_TOKEN": "secret-token"},
    )

    assert '"state_id": "abc"' in read_protected_text(root_dir, ".agent/state.json")


def test_grant_temporarily_allows_write_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)
    protect_file(root_dir, ".agent/plan.yaml", "plan-token")

    grant_file_lock(root_dir, ".agent/plan.yaml", "plan-token", ttl_seconds=30)
    write_protected_text(root_dir, ".agent/plan.yaml", "task_id: demo\nsteps: []\n")
    assert read_protected_text(root_dir, ".agent/plan.yaml") == "task_id: demo\nsteps: []\n"

    revoke_file_lock(root_dir, ".agent/plan.yaml")
    with pytest.raises(PermissionError):
        write_protected_text(root_dir, ".agent/plan.yaml", "task_id: changed\nsteps: []\n")


def test_state_repository_save_uses_managed_file_when_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)
    protect_file(root_dir, ".agent/state.json", "secret-token")

    saved = save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "VERIFY", "fuse": "enabled"})
    loaded = load_state(root_dir)

    assert saved["state_id"] == loaded["state_id"]
    assert StateRepository(root_dir).load().stage == "VERIFY"


def test_plan_repository_writes_managed_file_when_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)
    protect_file(root_dir, ".agent/plan.yaml", "plan-token", token_env="PLAN_WRITE_TOKEN")

    repository = PlanRepository(root_dir)
    repository.save_steps("password-reset", [])

    assert resolve_protected_path(root_dir, ".agent/plan.yaml").read_text(encoding="utf-8") == "task_id: password-reset\nsteps: []\n"


def test_delete_protected_file_requires_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    target = root_dir / ".agent" / "plan.yaml"
    target.write_text("task_id: demo\nsteps: []\n", encoding="utf-8")
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)
    protect_file(root_dir, ".agent/plan.yaml", "plan-token")

    with pytest.raises(PermissionError):
        delete_protected_file(root_dir, ".agent/plan.yaml")

    delete_protected_file(root_dir, ".agent/plan.yaml", token="plan-token")
    assert not resolve_protected_path(root_dir, ".agent/plan.yaml").exists()


def test_lock_status_reports_managed_paths_and_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: True)
    result = protect_file(root_dir, ".agent/state.json", "state-token")
    grant_file_lock(root_dir, ".agent/state.json", "state-token", ttl_seconds=30)

    status = lock_status(root_dir)

    assert status["files"][0]["path"] == ".agent/state.json"
    assert status["files"][0]["mode"] == "fuse"
    assert status["files"][0]["grant_active"] is True
    assert status["files"][0]["managed_path"] == result["managed_path"]
    assert (current_managed_state_dir(root_dir) / "file-lock-grants" / ".agent__state.json.json").exists()


def test_protect_file_fails_closed_without_fuse_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    monkeypatch.setattr("agent_guard_file_lock.core.fuse_runtime_available", lambda: False)

    with pytest.raises(RuntimeError, match="FUSE runtime is unavailable"):
        protect_file(root_dir, ".agent/state.json", "state-token")

    assert load_state(root_dir)["fuse"] == "disabled"


def test_load_manifest_migrates_legacy_workspace_lock_files(monkeypatch: pytest.MonkeyPatch) -> None:
    root_dir = make_temp_repo()
    state = load_state(root_dir)
    managed_dir = current_managed_state_dir(root_dir)
    legacy_manifest = root_dir / ".agent" / "locks" / "manifest.json"
    legacy_grants_dir = root_dir / ".agent" / "locks" / "grants"
    legacy_grants_dir.mkdir(parents=True, exist_ok=True)
    legacy_manifest.parent.mkdir(parents=True, exist_ok=True)
    legacy_manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    ".agent/plan.yaml": {
                        "path": ".agent/plan.yaml",
                        "mode": "fuse",
                        "token_hash": "abc",
                        "token_env": "PLAN_TOKEN",
                        "managed_path": str(managed_dir / "plan.yaml"),
                        "mount_path": ".agent/.mount/plan.yaml",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (legacy_grants_dir / ".agent__plan.yaml.json").write_text(
        json.dumps(
            {
                "path": ".agent/plan.yaml",
                "token_hash": "abc",
                "expires_at": "2999-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = load_manifest(root_dir)

    assert state["state_id"]
    assert ".agent/plan.yaml" in manifest.files
    assert (managed_dir / "file-lock.json").exists()
    assert (managed_dir / "file-lock-grants" / ".agent__plan.yaml.json").exists()
    assert not legacy_manifest.exists()
