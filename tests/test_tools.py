import pytest

from coding_agent.tools import make_tools


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")
    return {t.name: t for t in make_tools(tmp_path)}


def test_read_file_shows_line_numbers(tools):
    assert tools["read_file"].invoke({"path": "app.py"}).splitlines()[1] == "   2  y = 2"


def test_path_outside_repo_is_rejected(tools):
    with pytest.raises(ValueError, match="außerhalb"):
        tools["read_file"].invoke({"path": "../secret.txt"})


def test_edit_file_requires_unique_match(tools, tmp_path):
    assert "2-mal" in tools["edit_file"].invoke({"path": "app.py", "old_text": "x = 1", "new_text": "x = 3"})
    assert tools["edit_file"].invoke({"path": "app.py", "old_text": "y = 2", "new_text": "y = 5"}) == "app.py geändert."
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 1\ny = 5\nx = 1\n"


def test_search_code_finds_matches(tools):
    assert tools["search_code"].invoke({"pattern": r"y = \d"}) == "app.py:2: y = 2"


def test_run_tests_reports_exit_code(tools, tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert tools["run_tests"].invoke({}).startswith("Exit-Code: 0")
