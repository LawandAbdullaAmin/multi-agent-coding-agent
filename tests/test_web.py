import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from coding_agent import runs
from coding_agent.web import server
from coding_agent.web.events import EventTranslator, summarize_tests


class FakeTeam:
    """Replaces the team graph: changes a file, pauses for approval and then continues."""

    def __init__(self) -> None:
        self.workspace: Path | None = None
        self.waiting = False
        self.review = None

    def build(self, workspace, *args, **kwargs):
        self.workspace = workspace
        return self

    def stream(self, inputs, config, **kwargs):
        if isinstance(inputs, dict):  # first start
            yield (), {"supervisor": {"next": "developer", "instruction": "Fix divide"}}
            call = AIMessage("", tool_calls=[{"id": "1", "name": "edit_file", "args": {"path": "calculator.py"}}])
            yield ("developer:a",), {"model": {"messages": [call]}}
            (self.workspace / "calculator.py").write_text("# fixed\n", encoding="utf-8")
            yield ("developer:a",), {"tools": {"messages": [ToolMessage("calculator.py changed.", tool_call_id="1")]}}
            yield (), {"developer": {"reports": [{"agent": "developer", "model": "fake", "result": "Done"}]}}
            yield (), {"supervisor": {"next": "finish", "summary": "All done"}}
            self.waiting = True
        else:  # continuation after approval
            self.waiting, self.review = False, inputs.resume["action"]
            yield (), {"review": {"review": self.review}}

    def get_state(self, config):
        return SimpleNamespace(interrupts=("approval",) if self.waiting else (),
                               values={"summary": "All done", "tests_passed": True, "review": self.review})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / ".runs")
    for module in (runs, server):
        monkeypatch.setattr(module, "WORKSPACES_DIR", tmp_path / "workspaces")
    fake = FakeTeam()
    monkeypatch.setattr(server, "build_team_graph", fake.build)
    with TestClient(server.app) as test_client:
        yield test_client


def wait_for(session, event_type, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        types = [e["type"] for e in session.events]
        if event_type in types and not session.busy:
            return types
        time.sleep(0.05)
    raise AssertionError(f"{event_type} not received: {[e['type'] for e in session.events]}")


def test_index_and_projects(client):
    assert "Coding Agent" in client.get("/").text
    projects = client.get("/api/projects").json()
    assert {"task:calculator", "task:roman"} <= {p["id"] for p in projects}
    assert "path" not in projects[0]


def test_full_run_with_approval(client, tmp_path):
    run_id = client.post("/api/runs", json={"project": "task:calculator", "task": "Fix", "sandbox": False}).json()["id"]
    session = server.sessions[run_id]

    types = wait_for(session, "review")
    assert [t for t in types if t != "stats"] == ["run", "dispatch", "action", "report", "dispatch", "review"]
    review = next(e for e in session.events if e["type"] == "review")
    assert [(f["path"], f["new"], f["added"]) for f in review["files"]] == [("calculator.py", False, 1)]
    assert review["files"][0]["removed"] > 0
    assert "+# fixed" in review["diff"]

    assert client.post(f"/api/runs/{run_id}/decision", json={"action": "approve"}).json() == {"ok": True}
    wait_for(session, "done")
    done = session.events[-1]
    assert (done["type"], done["outcome"], done["files"]) == ("done", "approve", ["calculator.py"])
    assert (Path(session.run.repo) / "calculator.py").read_text(encoding="utf-8") == "# fixed\n"
    # The benchmark task itself stays unchanged because the interface works on a copy.
    assert "# fixed" not in (runs.PROJECT_DIR / "benchmark" / "tasks" / "calculator" / "repo" / "calculator.py").read_text(encoding="utf-8")


def test_decision_while_busy_or_unknown(client):
    assert client.post("/api/runs/does-not-exist/decision", json={"action": "approve"}).status_code == 404
    assert client.post("/api/runs", json={"project": "does-not-exist", "task": "x"}).status_code == 404


def test_translator_humanizes_tools():
    translator = EventTranslator()
    call = AIMessage("", tool_calls=[{"id": "7", "name": "run_tests", "args": {}}])
    assert translator.translate(("tester:b",), "model", {"messages": [call]}) == [
        {"type": "action", "agent": "tester", "tool": "run_tests", "text": "Runs all tests"}]
    result = ToolMessage("Exit code: 1\n..F.F.\n2 failed, 4 passed in 0.1s", tool_call_id="7")
    assert translator.translate(("tester:b",), "tools", {"messages": [result]}) == [
        {"type": "observation", "agent": "tester", "text": "2 of 6 tests failed", "ok": False}]
    denied = ToolMessage("Error: test_a.py must not be changed.", name="edit_file", tool_call_id="8",
                         status="error")
    assert translator.translate(("developer:c",), "tools", {"messages": [denied]}) == [
        {"type": "observation", "agent": "developer", "text": "Write protection kicked in: access denied", "ok": False}]


def test_summarize_tests():
    assert summarize_tests("Exit code: 0\n6 passed in 0.02s") == ("6 tests passed", True)
    assert summarize_tests("Exit code: 2\n1 error in 0.1s") == ("1 of 1 tests failed", False)
    assert summarize_tests("Exit code: 4\nfile not found") == ("Tests could not be run", False)
