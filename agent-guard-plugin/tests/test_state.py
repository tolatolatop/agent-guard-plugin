"""Tests for test state."""
import os

import pytest

from agent_guard.domain.policies import StageExitPolicyService
from agent_guard.jobs import load_jobs
from agent_guard.state import (
    AGENT_GITIGNORE_CONTENT,
    agent_gitignore_path,
    current_managed_state_dir,
    DEFAULT_JOBS,
    DEFAULT_STATE,
    ensure_agent_files,
    load_stage_artifact_snapshot,
    load_state,
    load_task_session,
    managed_state_dir,
    save_state,
)

from .helpers import make_temp_repo


def write_repo_workflow(root_dir, workflow_id: str, stages_yaml: str) -> None:
    workflows_dir = root_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / f"{workflow_id}.workflow.yaml").write_text(
        "version: 2\n"
        "workflow:\n"
        f"  id: {workflow_id}\n"
        "  title: Pattern Workflow\n"
        "  description: Pattern workflow for tests.\n"
        "  entry: IDLE\n"
        "globals:\n"
        "  protected:\n"
        "    - .agent/state.json\n"
        "stages:\n"
        "  IDLE:\n"
        "    goal: Idle\n"
        "    plan: deny\n"
        "    allow:\n"
        "      write:\n"
        "        - .agent/**\n"
        "      actions:\n"
        "        - inspect state\n"
        "      stop: true\n"
        "      human: true\n"
        "    deny:\n"
        "      write: []\n"
        "      actions: []\n"
        "    enter: []\n"
        "    exit: []\n"
        "    expect: []\n"
        "    next: []\n"
        f"{stages_yaml}",
        encoding="utf-8",
    )


def test_state_defaults_to_idle_when_agent_dir_is_missing() -> None:
    """Test that state defaults to idle when agent dir is missing."""
    root_dir = make_temp_repo()
    for child in (root_dir / ".agent").rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted((root_dir / ".agent").rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    (root_dir / ".agent").rmdir()

    state = load_state(root_dir)
    assert state["stage"] == DEFAULT_STATE["stage"]
    assert state["state_id"]
    assert managed_state_dir(state["state_id"]).is_dir()
    assert load_jobs(root_dir) == DEFAULT_JOBS


def test_state_loads_defaults_after_init() -> None:
    """Test that state loads defaults after init."""
    root_dir = make_temp_repo()
    state = load_state(root_dir)
    assert state["stage"] == DEFAULT_STATE["stage"]
    assert state["state_id"]
    assert managed_state_dir(state["state_id"]).is_dir()


def test_init_creates_agent_artifacts_directory() -> None:
    """Test that init creates agent artifacts directory."""
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


def test_init_creates_agent_gitignore_file() -> None:
    """Test that init creates .agent/.gitignore for workspace-local state."""
    root_dir = make_temp_repo()

    gitignore_file = agent_gitignore_path(root_dir)

    assert gitignore_file.exists()
    assert gitignore_file.read_text(encoding="utf-8") == AGENT_GITIGNORE_CONTENT


def test_ensure_agent_files_bootstraps_gitignore_for_fresh_workspace() -> None:
    """Fresh workspaces should receive the standard .agent gitignore file."""
    root_dir = make_temp_repo()
    extra_root = root_dir / "fresh-gitignore"
    extra_root.mkdir()

    ensure_agent_files(extra_root)

    assert agent_gitignore_path(extra_root).read_text(encoding="utf-8") == AGENT_GITIGNORE_CONTENT


def test_state_saves_and_reloads_updates() -> None:
    """Test that state saves and reloads updates."""
    root_dir = make_temp_repo()
    next_state = {**DEFAULT_STATE, "stage": "RED_TEST", "current_step": "red-001"}
    saved = save_state(root_dir, next_state)
    loaded = load_state(root_dir)
    assert loaded["stage"] == "RED_TEST"
    assert loaded["current_step"] == "red-001"
    assert loaded["state_id"] == saved["state_id"]
    assert managed_state_dir(saved["state_id"]).is_dir()


def test_save_state_preserves_existing_state_when_atomic_replace_fails(
    monkeypatch,
) -> None:
    """A failed atomic replace must leave the previous state.json intact."""
    root_dir = make_temp_repo()
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "CLARIFYING"})

    original_atomic_write = __import__("agent_guard.managed_documents", fromlist=["atomic_write_text"]).atomic_write_text

    def fail_state_write(target, content, *, encoding="utf-8"):
        if target.name == "state.json":
            raise OSError("boom")
        return original_atomic_write(target, content, encoding=encoding)

    monkeypatch.setattr("agent_guard.managed_documents.atomic_write_text", fail_state_write)

    with pytest.raises(OSError):
        save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "VERIFY"})

    assert load_state(root_dir)["stage"] == "CLARIFYING"


def test_state_loads_structured_task_session() -> None:
    """Test that state exposes a structured task session aggregate."""
    root_dir = make_temp_repo()
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "VERIFY"})

    session = load_task_session(root_dir)
    assert session.task_id == "password-reset"
    assert session.stage == "VERIFY"
    assert session.state_id is not None


def test_state_drops_legacy_step_fields_when_loading_and_saving() -> None:
    """Test that legacy step fields are ignored on load and removed on save."""
    root_dir = make_temp_repo()
    legacy_state = {
        **DEFAULT_STATE,
        "task_id": "password-reset",
        "completed_steps": ["red-001"],
        "remaining_steps": ["green-001"],
    }
    save_state(root_dir, legacy_state)

    state = load_state(root_dir)
    assert "completed_steps" not in state
    assert "remaining_steps" not in state
    assert state["state_id"]


def test_state_load_backfills_missing_state_id_and_creates_managed_state_dir() -> None:
    """Existing state.json files should be migrated with a stable state_id."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "state.json").write_text(
        '{"task_id": "password-reset", "workflow_id": null, "stage": "VERIFY", "current_step": null, "can_finalize": false, "last_verification": null, "needs_human": false}\n',
        encoding="utf-8",
    )

    state = load_state(root_dir)

    assert state["state_id"]
    assert managed_state_dir(state["state_id"]).is_dir()
    reloaded = load_state(root_dir)
    assert reloaded["state_id"] == state["state_id"]


def test_current_managed_state_dir_returns_directory_for_current_workspace() -> None:
    """The friendly helper should return the stable managed state directory."""
    root_dir = make_temp_repo()

    state = load_state(root_dir)
    managed_dir = current_managed_state_dir(root_dir)

    assert managed_dir == managed_state_dir(state["state_id"])
    assert managed_dir.is_dir()


def test_state_load_reports_friendly_message_when_json_is_invalid() -> None:
    """Test that invalid state JSON reports a repair-required message."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "state.json").write_text("{invalid\n", encoding="utf-8")

    try:
        load_state(root_dir)
    except RuntimeError as exc:
        assert "appears damaged" in str(exc)
        assert "cannot continue" in str(exc)
        assert "state.json" in str(exc)
    else:
        raise AssertionError("Expected invalid state JSON to fail")


def test_state_load_reports_friendly_message_when_required_key_is_missing() -> None:
    """Test that missing required keys are reported as corruption."""
    root_dir = make_temp_repo()
    (root_dir / ".agent" / "state.json").write_text('{"task_id": null}\n', encoding="utf-8")

    try:
        load_state(root_dir)
    except RuntimeError as exc:
        assert "appears damaged" in str(exc)
        assert "cannot continue" in str(exc)
        assert "Missing required key" in str(exc)
    else:
        raise AssertionError("Expected invalid state shape to fail")


def test_stage_artifact_snapshot_tracks_stage_entry() -> None:
    """Test that stage artifact snapshots are recorded when the stage changes."""
    root_dir = make_temp_repo()
    snapshot = load_stage_artifact_snapshot(root_dir)
    assert snapshot["stage"] == "IDLE"

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "REVIEW"})
    snapshot = load_stage_artifact_snapshot(root_dir)

    assert snapshot["stage"] == "REVIEW"
    assert snapshot["entered_at"] is not None
    assert ".agent/artifacts/review.md" in snapshot["artifacts"]
    assert snapshot["artifacts"][".agent/artifacts/review.md"]["mtime_ns"] is None


def test_stage_exit_policy_service_reports_missing_stale_and_mismatched_artifacts() -> None:
    """Test that stage exit policy reports all required-artifact failure modes."""
    root_dir = make_temp_repo()
    service = StageExitPolicyService(root_dir)

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "REVIEW"})
    failures = service.exit_failures("REVIEW")
    assert any("must exist and be updated after entering REVIEW" in failure for failure in failures)

    review_artifact = root_dir / ".agent" / "artifacts" / "review.md"
    review_artifact.write_text("stale\n", encoding="utf-8")
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "GREEN_IMPL"})
    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "REVIEW"})
    failures = service.exit_failures("REVIEW")
    assert any("must be updated after entering REVIEW" in failure for failure in failures)

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "stage": "NEEDS_FAILURE_ANALYSIS"})
    analysis_artifact = root_dir / ".agent" / "artifacts" / "failure-analysis.md"
    analysis_artifact.write_text("wrong header\n", encoding="utf-8")
    fresh_mtime = analysis_artifact.stat().st_mtime_ns + 1_000_000
    os.utime(analysis_artifact, ns=(fresh_mtime, fresh_mtime))
    failures = service.exit_failures("NEEDS_FAILURE_ANALYSIS")
    assert any("Failure Summary" in failure for failure in failures)


def test_stage_exit_policy_supports_directory_artifact_patterns() -> None:
    """A directory artifact should pass when any descendant updates after stage entry."""
    root_dir = make_temp_repo()
    write_repo_workflow(
        root_dir,
        "patterns",
        "  DIR_OUTPUT:\n"
        "    goal: Require output directory updates.\n"
        "    plan: deny\n"
        "    allow:\n"
        "      write:\n"
        "        - output/**\n"
        "      actions:\n"
        "        - write outputs\n"
        "      stop: true\n"
        "      human: true\n"
        "    deny:\n"
        "      write: []\n"
        "      actions: []\n"
        "    enter: []\n"
        "    exit:\n"
        "      - output\n"
        "    expect: []\n"
        "    next: []\n",
    )
    service = StageExitPolicyService(root_dir)
    output_file = root_dir / "output" / "review.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("before\n", encoding="utf-8")

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "workflow_id": "patterns", "stage": "DIR_OUTPUT"})
    failures = service.exit_failures("DIR_OUTPUT")
    assert any("output must be updated after entering DIR_OUTPUT" in failure for failure in failures)

    output_file.write_text("after\n", encoding="utf-8")
    fresh_mtime = output_file.stat().st_mtime_ns + 1_000_000
    os.utime(output_file, ns=(fresh_mtime, fresh_mtime))
    assert service.exit_failures("DIR_OUTPUT") == []


def test_stage_exit_policy_skips_broken_symlinks_in_directory_artifacts() -> None:
    """A broken symlink inside a directory artifact should not crash stage exit checks."""
    root_dir = make_temp_repo()
    write_repo_workflow(
        root_dir,
        "patterns",
        "  DIR_OUTPUT:\n"
        "    goal: Require output directory updates.\n"
        "    plan: deny\n"
        "    allow:\n"
        "      write:\n"
        "        - output/**\n"
        "      actions:\n"
        "        - write outputs\n"
        "      stop: true\n"
        "      human: true\n"
        "    deny:\n"
        "      write: []\n"
        "      actions: []\n"
        "    enter: []\n"
        "    exit:\n"
        "      - output\n"
        "    expect: []\n"
        "    next: []\n",
    )
    service = StageExitPolicyService(root_dir)
    output_dir = root_dir / "output"
    output_dir.mkdir()
    output_file = output_dir / "review.md"
    output_file.write_text("after\n", encoding="utf-8")
    (output_dir / "broken-link").symlink_to("missing-target")

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "workflow_id": "patterns", "stage": "DIR_OUTPUT"})
    fresh_mtime = output_file.stat().st_mtime_ns + 1_000_000
    os.utime(output_file, ns=(fresh_mtime, fresh_mtime))

    assert service.exit_failures("DIR_OUTPUT") == []


def test_stage_exit_policy_supports_recursive_glob_artifact_patterns() -> None:
    """A recursive glob artifact should pass when one matching descendant is created in-stage."""
    root_dir = make_temp_repo()
    write_repo_workflow(
        root_dir,
        "patterns",
        "  GLOB_OUTPUT:\n"
        "    goal: Require recursive output artifacts.\n"
        "    plan: deny\n"
        "    allow:\n"
        "      write:\n"
        "        - output/**\n"
        "      actions:\n"
        "        - write outputs\n"
        "      stop: true\n"
        "      human: true\n"
        "    deny:\n"
        "      write: []\n"
        "      actions: []\n"
        "    enter: []\n"
        "    exit:\n"
        "      - output/**\n"
        "    expect: []\n"
        "    next: []\n",
    )
    service = StageExitPolicyService(root_dir)

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "workflow_id": "patterns", "stage": "GLOB_OUTPUT"})
    nested_output = root_dir / "output" / "nested" / "result.log"
    nested_output.parent.mkdir(parents=True, exist_ok=True)
    nested_output.write_text("ok\n", encoding="utf-8")

    assert service.exit_failures("GLOB_OUTPUT") == []


def test_stage_exit_policy_supports_nested_glob_regex_artifact_patterns() -> None:
    """A nested glob artifact with content validation should match any matching file."""
    root_dir = make_temp_repo()
    write_repo_workflow(
        root_dir,
        "patterns",
        "  NESTED_REVIEW:\n"
        "    goal: Require nested review artifact.\n"
        "    plan: deny\n"
        "    allow:\n"
        "      write:\n"
        "        - output/**\n"
        "      actions:\n"
        "        - write outputs\n"
        "      stop: true\n"
        "      human: true\n"
        "    deny:\n"
        "      write: []\n"
        "      actions: []\n"
        "    enter: []\n"
        "    exit:\n"
        "      - path: output/*/review.md\n"
        "        matches: '^# Review'\n"
        "        display: 'review artifact must start with # Review.'\n"
        "    expect: []\n"
        "    next: []\n",
    )
    service = StageExitPolicyService(root_dir)

    save_state(root_dir, {**DEFAULT_STATE, "task_id": "password-reset", "workflow_id": "patterns", "stage": "NESTED_REVIEW"})
    review_file = root_dir / "output" / "run-1" / "review.md"
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_file.write_text("wrong header\n", encoding="utf-8")
    bad_mtime = review_file.stat().st_mtime_ns + 1_000_000
    os.utime(review_file, ns=(bad_mtime, bad_mtime))

    failures = service.exit_failures("NESTED_REVIEW")
    assert failures == ["review artifact must start with # Review."]

    review_file.write_text("# Review\nok\n", encoding="utf-8")
    good_mtime = review_file.stat().st_mtime_ns + 1_000_000
    os.utime(review_file, ns=(good_mtime, good_mtime))
    assert service.exit_failures("NESTED_REVIEW") == []
