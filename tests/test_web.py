import json
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
    """Ersetzt den Team-Graphen: ändert eine Datei, pausiert zur Freigabe und läuft danach weiter."""

    def __init__(self) -> None:
        self.workspace: Path | None = None
        self.waiting = False
        self.review = None

    def build(self, workspace, *args, **kwargs):
        self.workspace = workspace
        return self

    def stream(self, inputs, config, **kwargs):
        if isinstance(inputs, dict):  # erster Start
            yield (), {"supervisor": {"next": "developer", "instruction": "Behebe divide"}}
            call = AIMessage("", tool_calls=[{"id": "1", "name": "edit_file", "args": {"path": "calculator.py"}}])
            yield ("developer:a",), {"model": {"messages": [call]}}
            (self.workspace / "calculator.py").write_text("# behoben\n", encoding="utf-8")
            yield ("developer:a",), {"tools": {"messages": [ToolMessage("calculator.py geändert.", tool_call_id="1")]}}
            yield (), {"developer": {"reports": [{"agent": "developer", "model": "fake", "result": "Fertig"}]}}
            yield (), {"supervisor": {"next": "finish", "summary": "Alles erledigt"}}
            self.waiting = True
        else:  # Fortsetzung nach der Freigabe
            self.waiting, self.review = False, inputs.resume["action"]
            yield (), {"review": {"review": self.review}}

    def get_state(self, config):
        return SimpleNamespace(interrupts=("freigabe",) if self.waiting else (),
                               values={"summary": "Alles erledigt", "tests_passed": True, "review": self.review})


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module, name in ((runs, "RUNS_DIR"), (server, "RUNS_DIR")):
        monkeypatch.setattr(module, name, tmp_path / ".runs")
    for module in (runs, server):
        monkeypatch.setattr(module, "WORKSPACES_DIR", tmp_path / "workspaces")
    monkeypatch.setattr(server, "DEMO_DIR", tmp_path / "demo")
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
    raise AssertionError(f"{event_type} nicht erhalten: {[e['type'] for e in session.events]}")


def test_index_and_projects(client):
    assert "Coding-Agent" in client.get("/").text
    projects = client.get("/api/projects").json()
    assert {"example:calculator", "task:roman"} <= {p["id"] for p in projects}
    assert "path" not in projects[0]


def test_full_run_with_approval(client, tmp_path):
    run_id = client.post("/api/runs", json={"project": "example:calculator", "task": "Fix", "sandbox": False}).json()["id"]
    session = server.sessions[run_id]

    types = wait_for(session, "review")
    assert [t for t in types if t != "stats"] == ["run", "dispatch", "action", "report", "dispatch", "review"]
    review = next(e for e in session.events if e["type"] == "review")
    assert [(f["path"], f["new"], f["added"]) for f in review["files"]] == [("calculator.py", False, 1)]
    assert review["files"][0]["removed"] > 0
    assert "+# behoben" in review["diff"]

    assert client.post(f"/api/runs/{run_id}/decision", json={"action": "approve"}).json() == {"ok": True}
    wait_for(session, "done")
    done = session.events[-1]
    assert (done["type"], done["outcome"], done["files"]) == ("done", "approve", ["calculator.py"])
    assert (Path(session.run.repo) / "calculator.py").read_text(encoding="utf-8") == "# behoben\n"
    # Das Beispiel selbst bleibt unverändert, weil die Oberfläche auf einer Kopie arbeitet.
    assert "# behoben" not in (runs.PROJECT_DIR / "examples" / "calculator" / "calculator.py").read_text(encoding="utf-8")
    # Der Lauf wurde für den Demo-Modus aufgezeichnet.
    recording = tmp_path / ".runs" / f"{run_id}.events.jsonl"
    assert [json.loads(line)["type"] for line in recording.read_text(encoding="utf-8").splitlines()][-1] == "done"


def test_decision_while_busy_or_unknown(client):
    assert client.post("/api/runs/gibt-es-nicht/decision", json={"action": "approve"}).status_code == 404
    assert client.post("/api/runs", json={"project": "gibt-es-nicht", "task": "x"}).status_code == 404


def test_demo_replays_recording(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEMO_MAX_PAUSE", 0.01)
    (tmp_path / "demo").mkdir()
    events = [{"t": 0, "type": "run", "id": "x", "task": "Fix", "project": "roman", "models": {}, "demo": False},
              {"t": 1, "type": "dispatch", "agent": "explorer", "text": "Schau dir das an"},
              {"t": 9, "type": "review", "summary": "ok", "tests_passed": True, "files": [], "diff": ""},
              {"t": 12, "type": "decision", "action": "approve", "text": ""},
              {"t": 13, "type": "done", "outcome": "approve", "files": ["roman.py"]}]
    (tmp_path / "demo" / "roman.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    assert client.get("/api/status").json()["demos"] == ["roman"]
    session = server.sessions[client.post("/api/demos/roman").json()["id"]]
    assert wait_for(session, "review") == ["run", "dispatch", "review"]
    assert session.events[0]["demo"] is True

    client.post(f"/api/runs/{session.id}/decision", json={"action": "approve"})
    assert session.events[-1] == {**session.events[-1], "type": "done", "outcome": "approve", "files": [], "demo": True}


def test_translator_humanizes_tools():
    translator = EventTranslator()
    call = AIMessage("", tool_calls=[{"id": "7", "name": "run_tests", "args": {}}])
    assert translator.translate(("tester:b",), "model", {"messages": [call]}) == [
        {"type": "action", "agent": "tester", "tool": "run_tests", "text": "Führt alle Tests aus"}]
    result = ToolMessage("Exit-Code: 1\n..F.F.\n2 failed, 4 passed in 0.1s", tool_call_id="7")
    assert translator.translate(("tester:b",), "tools", {"messages": [result]}) == [
        {"type": "observation", "agent": "tester", "text": "2 von 6 Tests fehlgeschlagen", "ok": False}]


def test_summarize_tests():
    assert summarize_tests("Exit-Code: 0\n6 passed in 0.02s") == ("6 Tests bestanden", True)
    assert summarize_tests("Exit-Code: 2\n1 error in 0.1s") == ("1 von 1 Tests fehlgeschlagen", False)
    assert summarize_tests("Exit-Code: 4\nfile not found") == ("Tests konnten nicht ausgeführt werden", False)
