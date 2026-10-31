"""Gespeicherte Läufe: Einstellungen und Checkpoints, damit Läufe später fortgesetzt werden können.

Pro Lauf liegt in .runs/ eine JSON-Datei mit den Einstellungen. Die Zwischenstände
des Graphen speichert LangGraph in .runs/checkpoints.sqlite (thread_id = Lauf-ID).
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

RUNS_DIR = Path(__file__).resolve().parent.parent / ".runs"


@dataclass
class Run:
    id: str
    task: str
    repo: str
    workspace: str
    mode: str
    sandbox: bool
    human_review: bool
    in_place: bool


def save_run(run: Run) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"{run.id}.json").write_text(json.dumps(asdict(run), indent=2, ensure_ascii=False), encoding="utf-8")


def load_run(run_id: str) -> Run:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Kein gespeicherter Lauf mit der ID '{run_id}' in {RUNS_DIR}.")
    return Run(**json.loads(path.read_text(encoding="utf-8")))


def open_checkpointer() -> SqliteSaver:
    RUNS_DIR.mkdir(exist_ok=True)
    # check_same_thread=False: LangGraph führt Knoten in mehreren Threads aus.
    return SqliteSaver(sqlite3.connect(RUNS_DIR / "checkpoints.sqlite", check_same_thread=False))
