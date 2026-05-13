import tempfile
from io import StringIO
from pathlib import Path

import yaml

from agent_guard.plan import plan_path
from agent_guard.state import load_state
from agent_guard.wizard import run_wizard, slugify_task_id


def make_repo() -> Path:
    return Path(tempfile.mkdtemp(prefix="agent-guard-wizard-"))


def test_slugify_task_id_normalizes_free_text() -> None:
    assert slugify_task_id("Init Video Clipper!") == "init-video-clipper"


def test_wizard_writes_state_and_plan_from_plain_streams() -> None:
    root = make_repo()
    answers = StringIO(
        "\n"
        "Build ffmpeg wrapper\n"
        "RED_TEST\n"
        "red-001\n"
        "tests/**\n"
        "src/**\n"
        "y\n"
    )

    result = run_wizard(root, answers, StringIO())

    assert result["task_id"] == slugify_task_id(root.name)
    state = load_state(root)
    assert state["stage"] == "RED_TEST"
    assert state["current_step"] == "red-001"
    assert state["allowed_paths"] == ["tests/**"]
    assert state["forbidden_paths"] == ["src/**"]
    assert result["plan_written"] == str(plan_path(root))

    plan = yaml.safe_load(plan_path(root).read_text(encoding="utf-8"))
    assert plan["task_id"] == state["task_id"]
    assert plan["steps"][0]["id"] == "red-001"
    assert plan["steps"][0]["goal"] == "Build ffmpeg wrapper"


def test_wizard_can_skip_plan_generation() -> None:
    root = make_repo()
    answers = StringIO(
        "video-clipper\n"
        "Scaffold project\n"
        "CLARIFYING\n"
        "\n"
        "\n"
        "\n"
        "n\n"
    )

    result = run_wizard(root, answers, StringIO())

    assert result["plan_written"] is None
    assert not plan_path(root).exists()
