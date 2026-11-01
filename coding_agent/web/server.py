"""Webserver der Oberfläche (FastAPI).

Ein Lauf des Teams läuft in einem Hintergrund-Thread. Jedes Ereignis wird in einer Liste
gesammelt und per Server-Sent Events an den Browser gestreamt.
"""

import asyncio
import difflib
import json
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command
from pydantic import BaseModel

from coding_agent.evaluate import estimate_cost, load_tasks
from coding_agent.runs import (
    WORKSPACES_DIR,
    Run,
    apply_changes,
    changed_files,
    copy_repo,
    diff_text,
    new_run,
    open_checkpointer,
    run_config,
    save_run,
)
from coding_agent.team import build_team_graph, model_names
from coding_agent.tools import docker_available, ensure_sandbox_image, read_text
from coding_agent.web.events import EventTranslator

STATIC_DIR = Path(__file__).resolve().parent / "static"
BUDGET_MODELS = {"fast": "gpt-4.1-mini", "strong": "gpt-4.1-mini"}


# --- Projekte -------------------------------------------------------------------

def list_projects() -> list[dict]:
    return [{"id": f"task:{t.name}", "name": t.name, "kind": t.kind, "difficulty": t.difficulty,
             "task": t.description, "path": t.path / "repo"} for t in load_tasks()]


def file_stats(original: Path, workspace: Path) -> list[dict]:
    stats = []
    for rel in changed_files(original, workspace):
        before = original / rel
        old = read_text(before).splitlines() if before.exists() else []
        lines = list(difflib.unified_diff(old, read_text(workspace / rel).splitlines(), lineterm=""))[2:]
        stats.append({"path": rel.as_posix(), "new": not before.exists(),
                      "added": sum(line.startswith("+") for line in lines),
                      "removed": sum(line.startswith("-") for line in lines)})
    return stats


# --- Sitzungen ------------------------------------------------------------------

class RunSession:
    """Ein Lauf des Teams: führt den Graphen aus und sammelt die Ereignisse, die der Browser abholt."""

    def __init__(self, run: Run, models: dict[str, str], project: str) -> None:
        self.id, self.run, self.models = run.id, run, models
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.started = time.time()
        self.busy = False
        self.cost, self.tokens = 0.0, 0
        self.translator = EventTranslator()
        self.emit({"type": "run", "id": run.id, "task": run.task, "project": project, "models": models})

    def emit(self, event: dict) -> None:
        with self.lock:
            self.events.append({"t": round(time.time() - self.started, 2), **event})

    def events_from(self, index: int) -> list[dict]:
        with self.lock:
            return self.events[index:]

    def start(self, inputs) -> None:
        self.busy = True
        threading.Thread(target=self._execute, args=(inputs,), daemon=True).start()

    def decide(self, action: str, feedback: str) -> None:
        if self.busy:
            raise HTTPException(409, "Das Team arbeitet noch.")
        self.emit({"type": "decision", "action": action, "text": feedback})
        self.start(Command(resume={"action": action, "feedback": feedback}))

    def _execute(self, inputs) -> None:
        run = self.run
        try:
            app = build_team_graph(Path(run.workspace), run.sandbox, run.human_review, open_checkpointer(), self.models)
            config = run_config(run.id, "coding-agent (web)", ["web"], {"lauf_id": run.id})
            base_cost, base_tokens = self.cost, self.tokens
            with get_usage_metadata_callback() as usage:
                for namespace, chunk in app.stream(inputs, config, stream_mode="updates", subgraphs=True):
                    for node, update in chunk.items():
                        if isinstance(update, dict):
                            for event in self.translator.translate(namespace, node, update):
                                self.emit(event)
                    cost = base_cost + (estimate_cost(usage.usage_metadata) or 0)
                    tokens = base_tokens + sum(u["input_tokens"] + u["output_tokens"]
                                               for u in usage.usage_metadata.values())
                    if tokens != self.tokens:
                        self.cost, self.tokens = cost, tokens
                        self.emit({"type": "stats", "cost": round(cost, 5), "tokens": tokens})

            state = app.get_state(config)
            original, workspace = Path(run.repo), Path(run.workspace)
            if state.interrupts:
                self.emit({"type": "review", "summary": state.values.get("summary", ""),
                           "tests_passed": state.values.get("tests_passed"),
                           "files": file_stats(original, workspace), "diff": diff_text(original, workspace)})
            elif state.values.get("review") == "approve":
                files = [f.as_posix() for f in apply_changes(original, workspace)]
                self.emit({"type": "done", "outcome": "approve", "files": files})
            else:
                self.emit({"type": "done", "outcome": "reject"})
        except Exception as e:  # Fehler sollen in der Oberfläche erscheinen, nicht den Server stoppen
            self.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            self.busy = False


sessions: dict[str, RunSession] = {}


# --- API --------------------------------------------------------------------------

class StartRequest(BaseModel):
    project: str
    task: str
    budget: bool = True
    sandbox: bool = True


class DecisionRequest(BaseModel):
    action: Literal["approve", "reject", "feedback"]
    feedback: str = ""


app = FastAPI(title="Coding-Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def no_cache(request, call_next):
    # Die Oberfläche wird oft geändert: Der Browser soll immer die aktuelle Version laden.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict:
    return {"docker": docker_available(), "models": model_names(), "budget_models": BUDGET_MODELS}


@app.get("/api/projects")
def projects() -> list[dict]:
    return [{k: v for k, v in p.items() if k != "path"} for p in list_projects()]


@app.post("/api/runs")
def start(request: StartRequest) -> dict:
    project = next((p for p in list_projects() if p["id"] == request.project), None)
    if project is None:
        raise HTTPException(404, "Unbekanntes Projekt.")
    if not request.task.strip():
        raise HTTPException(400, "Die Aufgabe ist leer.")
    if request.sandbox:
        ensure_sandbox_image()
    # Projekte werden kopiert, damit eine Freigabe nie den Benchmark verändert.
    repo = WORKSPACES_DIR / "web-repos" / f"{project['name']}-{time.strftime('%Y%m%d-%H%M%S')}"
    copy_repo(project["path"], repo)
    run = new_run(repo, request.task.strip(), sandbox=request.sandbox)
    save_run(run)
    session = RunSession(run, BUDGET_MODELS if request.budget else model_names(), project["name"])
    sessions[session.id] = session
    session.start({"task": run.task})
    return {"id": session.id}


@app.post("/api/runs/{session_id}/decision")
def decide(session_id: str, request: DecisionRequest) -> dict:
    if session_id not in sessions:
        raise HTTPException(404, "Unbekannter Lauf.")
    if request.action == "feedback" and not request.feedback.strip():
        raise HTTPException(400, "Das Feedback ist leer.")
    sessions[session_id].decide(request.action, request.feedback.strip())
    return {"ok": True}


@app.get("/api/runs/{session_id}/events")
async def events(session_id: str) -> StreamingResponse:
    if session_id not in sessions:
        raise HTTPException(404, "Unbekannter Lauf.")
    session = sessions[session_id]

    async def stream():
        index, idle = 0, 0
        while True:
            new = session.events_from(index)
            for event in new:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            index += len(new)
            idle = 0 if new else idle + 1
            if idle and idle % 75 == 0:
                yield ": ping\n\n"  # hält die Verbindung offen, während das Team arbeitet
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
