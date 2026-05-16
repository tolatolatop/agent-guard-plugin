"""Tests for test wizard."""
import tempfile
from io import StringIO
from pathlib import Path

import yaml

from agent_guard.plan import plan_path
from agent_guard.state import load_state
from agent_guard.wizard import run_wizard, slugify_task_id


def make_repo() -> Path:
    """Helper for make repo."""
    return Path(tempfile.mkdtemp(prefix="agent-guard-wizard-"))


def write_research_workflow(root: Path) -> None:
    """Write one minimal named workflow for wizard selection tests."""
    (root / "research.workflow.yaml").write_text(
        "\n".join(
            [
                "version: 2",
                "workflow:",
                "  id: research",
                "  title: Research Workflow",
                "  entry: DISCOVER",
                "globals:",
                "  protected:",
                "    - .agent/state.json",
                "  sensitive: []",
                "  failures:",
                "    repeat_threshold: 2",
                "    fingerprint_roots:",
                "      - notes",
                "  finalize:",
                "    require:",
                "      - all_plan_steps_terminal",
                "    messages: {}",
                "  wizard:",
                "    start_stages:",
                "      - DISCOVER",
                "  session_start:",
                "    navigator_skill: using-workflow",
                "  install:",
                "    skills:",
                "      match: []",
                "      exclude_match: []",
                "stages:",
                "  DISCOVER:",
                "    goal: Gather evidence and frame the research task.",
                "    plan: create",
                "    allow:",
                "      write:",
                "        - notes/**",
                "      actions:",
                "        - inspect sources",
                "      stop: true",
                "      human: true",
                "    deny:",
                "      write: []",
                "      actions: []",
                "    enter: []",
                "    exit: []",
                "    expect: []",
                "    next: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_slugify_task_id_normalizes_free_text() -> None:
    """Test that slugify task id normalizes free text."""
    assert slugify_task_id("Init Video Clipper!") == "init-video-clipper"


def test_wizard_writes_state_and_plan_from_plain_streams() -> None:
    """Test that wizard writes state and plan from plain streams."""
    root = make_repo()
    answers = StringIO(
        "\n"
        "Build ffmpeg wrapper\n"
        "RED_TEST\n"
        "red-001\n"
        "y\n"
    )

    result = run_wizard(root, answers, StringIO())

    assert result["task_id"] == slugify_task_id(root.name)
    state = load_state(root)
    assert state["stage"] == "RED_TEST"
    assert state["current_step"] == "red-001"
    assert result["plan_written"] == str(plan_path(root))

    plan = yaml.safe_load(plan_path(root).read_text(encoding="utf-8"))
    assert plan["task_id"] == state["task_id"]
    assert plan["steps"][0]["id"] == "red-001"
    assert plan["steps"][0]["goal"] == "Build ffmpeg wrapper"
    assert plan["steps"][0]["stage"] == "RED_TEST"
    assert plan["steps"][0]["status"] == "in_progress"


def test_wizard_can_skip_plan_generation() -> None:
    """Test that wizard can skip plan generation."""
    root = make_repo()
    answers = StringIO(
        "video-clipper\n"
        "Scaffold project\n"
        "CLARIFYING\n"
        "\n"
        "n\n"
    )

    result = run_wizard(root, answers, StringIO())

    assert result["plan_written"] is None
    assert not plan_path(root).exists()


def test_wizard_lists_named_workflows_and_binds_selected_workflow() -> None:
    """Test that wizard prompts for workflow choice when named workflows exist."""
    root = make_repo()
    write_research_workflow(root)
    output = StringIO()
    answers = StringIO(
        "research\n"
        "\n"
        "Investigate retrieval options\n"
        "\n"
        "\n"
        "n\n"
    )

    result = run_wizard(root, answers, output)

    assert "Workflow" in output.getvalue()
    assert result["workflow_id"] == "research"
    state = load_state(root)
    assert state["workflow_id"] == "research"
    assert state["stage"] == "DISCOVER"
