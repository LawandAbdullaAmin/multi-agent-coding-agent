import shutil

import pytest

from coding_agent.evaluate import estimate_cost, grade, load_tasks
from coding_agent.runs import copy_repo

TASKS = load_tasks()


def test_benchmark_has_tasks():
    assert len(TASKS) >= 10


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_unsolved_task_fails(task, tmp_path):
    """Every task must fail at first, otherwise it measures nothing."""
    copy_repo(task.path / "repo", tmp_path / "ws")
    passed, tests_modified, _ = grade(task, tmp_path / "ws", tmp_path / "grading", sandbox=False)
    assert not passed
    assert not tests_modified


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_reference_solution_passes(task, tmp_path):
    """Every task must be solvable with the reference solution, including the hidden tests."""
    copy_repo(task.path / "repo", tmp_path / "ws")
    shutil.copytree(task.path / "solution", tmp_path / "ws", dirs_exist_ok=True)
    passed, _, output = grade(task, tmp_path / "ws", tmp_path / "grading", sandbox=False)
    assert passed, output


def test_modified_tests_are_detected_and_ignored(tmp_path):
    task = next(t for t in TASKS if t.name == "calculator")
    copy_repo(task.path / "repo", tmp_path / "ws")
    # "Cheating": empty the test file so that nothing fails anymore
    (tmp_path / "ws" / "test_calculator.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    passed, tests_modified, _ = grade(task, tmp_path / "ws", tmp_path / "grading", sandbox=False)
    assert tests_modified
    assert not passed


def test_estimate_cost():
    usage = {"gpt-4.1-mini-2025-04-14": {"input_tokens": 1_000_000, "output_tokens": 500_000}}
    assert estimate_cost(usage) == pytest.approx(0.40 + 0.80)
    assert estimate_cost({"unknown": {"input_tokens": 1, "output_tokens": 1}}) is None
