from concurrent.futures import ThreadPoolExecutor

import pytest

from coding_agent.tools import docker_available, ensure_sandbox_image, make_tools


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\ny = 2\nx = 1\n", encoding="utf-8")
    return {t.name: t for t in make_tools(tmp_path, sandbox=False)}


def test_read_file_shows_line_numbers(tools):
    assert tools["read_file"].invoke({"path": "app.py"}).splitlines()[1] == "   2  y = 2"


def test_path_outside_repo_is_rejected(tools):
    assert "außerhalb" in tools["read_file"].invoke({"path": "../secret.txt"})


def test_edit_file_requires_unique_match(tools, tmp_path):
    assert "2-mal" in tools["edit_file"].invoke({"path": "app.py", "old_text": "x = 1", "new_text": "x = 3"})
    assert tools["edit_file"].invoke({"path": "app.py", "old_text": "y = 2", "new_text": "y = 5"}) == "app.py geändert."
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 1\ny = 5\nx = 1\n"


def test_parallel_edits_on_same_file_are_not_lost(tmp_path):
    lines = [f"value_{i} = {i}" for i in range(20)]
    (tmp_path / "many.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    edit = {t.name: t for t in make_tools(tmp_path, sandbox=False)}["edit_file"]
    edits = [{"path": "many.py", "old_text": f"value_{i} = {i}\n", "new_text": f"value_{i} = -{i}\n"}
             for i in range(20)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(edit.invoke, edits))
    content = (tmp_path / "many.py").read_text(encoding="utf-8")
    assert content == "".join(f"value_{i} = -{i}\n" for i in range(20))


def test_write_policy_blocks_writes(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    tools = {t.name: t for t in make_tools(tmp_path, sandbox=False, can_write=lambda rel: "Nur lesen.")}
    assert "darf nicht geändert werden. Nur lesen." in tools["edit_file"].invoke(
        {"path": "app.py", "old_text": "x = 1", "new_text": "x = 2"})
    assert "darf nicht" in tools["write_file"].invoke({"path": "neu.py", "content": "y = 1"})
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (tmp_path / "neu.py").exists()


def test_control_characters_are_rejected(tools, tmp_path):
    result = tools["edit_file"].invoke({"path": "app.py", "old_text": "y = 2", "new_text": "y = '10,05 \x1e'"})
    assert "Steuerzeichen" in result
    assert "Steuerzeichen" in tools["write_file"].invoke({"path": "neu.py", "content": "x = 1\x00"})
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "x = 1\ny = 2\nx = 1\n"
    assert "geändert" in tools["edit_file"].invoke({"path": "app.py", "old_text": "y = 2", "new_text": "y = '5 €'\t"})


def test_show_changes_lists_edits_and_new_files(tools):
    assert tools["show_changes"].invoke({}) == "Keine Änderungen."
    tools["edit_file"].invoke({"path": "app.py", "old_text": "y = 2", "new_text": "y = 5"})
    tools["write_file"].invoke({"path": "neu.py", "content": "z = 1\n"})
    changes = tools["show_changes"].invoke({})
    assert "-y = 2" in changes and "+y = 5" in changes and "+z = 1" in changes


def test_search_code_finds_matches(tools):
    assert tools["search_code"].invoke({"pattern": r"y = \d"}) == "app.py:2: y = 2"


def test_run_tests_reports_exit_code(tools, tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert tools["run_tests"].invoke({}).startswith("Exit-Code: 0")


@pytest.mark.skipif(not docker_available(), reason="Docker läuft nicht")
def test_sandbox_has_no_network_and_readonly_repo(tmp_path):
    ensure_sandbox_image()
    (tmp_path / "test_sandbox.py").write_text(
        "import pathlib, socket, pytest\n"
        "def test_no_network():\n"
        "    with pytest.raises(OSError):\n"
        "        socket.create_connection(('pypi.org', 443), timeout=3)\n"
        "def test_repo_is_readonly():\n"
        "    with pytest.raises(OSError):\n"
        "        pathlib.Path('hacked.txt').write_text('x')\n",
        encoding="utf-8",
    )
    run_tests = {t.name: t for t in make_tools(tmp_path)}["run_tests"]
    assert run_tests.invoke({}).startswith("Exit-Code: 0")
    assert not (tmp_path / "hacked.txt").exists()
