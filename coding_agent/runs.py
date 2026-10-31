"""Läufe: Arbeitskopie anlegen, Einstellungen und Checkpoints speichern, Änderungen übernehmen.

Pro Lauf liegt in .runs/ eine JSON-Datei mit den Einstellungen. Die Zwischenstände
des Graphen speichert LangGraph in .runs/checkpoints.sqlite (thread_id = Lauf-ID).
Gearbeitet wird auf einer Kopie des Repositorys unter workspaces/<lauf-id>.
"""

import difflib
import json
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from coding_agent.tools import IGNORED_DIRS, iter_files, read_text

PROJECT_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_DIR / ".runs"
WORKSPACES_DIR = PROJECT_DIR / "workspaces"


@dataclass
class Run:
    id: str
    task: str
    repo: str
    workspace: str
    sandbox: bool
    human_review: bool
    in_place: bool


def new_run(repo: Path, task: str, in_place: bool = False, auto_approve: bool = False, sandbox: bool = True) -> Run:
    repo = repo.resolve()
    run_id = f"{repo.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    workspace = repo if in_place else WORKSPACES_DIR / run_id
    if not in_place:
        shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    return Run(
        id=run_id, task=task, repo=str(repo), workspace=str(workspace), sandbox=sandbox, in_place=in_place,
        # Freigabe nur, wenn auf einer Kopie gearbeitet wird: Nur dann kann man Änderungen noch verwerfen.
        human_review=not auto_approve and not in_place,
    )


def changed_files(original: Path, workspace: Path) -> list[Path]:
    """Relative Pfade aller Dateien, die im Workspace neu oder geändert sind."""
    changed = []
    for file in iter_files(workspace):
        rel = file.relative_to(workspace)
        before = original / rel
        if not before.exists() or before.read_bytes() != file.read_bytes():
            changed.append(rel)
    return changed


def diff_text(original: Path, workspace: Path) -> str:
    lines = []
    for rel in changed_files(original, workspace):
        before = original / rel
        old = read_text(before).splitlines(keepends=True) if before.exists() else []
        new = read_text(workspace / rel).splitlines(keepends=True)
        lines.extend(difflib.unified_diff(old, new, f"a/{rel.as_posix()}", f"b/{rel.as_posix()}"))
    return "".join(lines)


def apply_changes(original: Path, workspace: Path) -> list[Path]:
    files = changed_files(original, workspace)
    for rel in files:
        target = original / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace / rel, target)
    return files


def save_run(run: Run) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"{run.id}.json").write_text(json.dumps(asdict(run), indent=2, ensure_ascii=False), encoding="utf-8")


def load_run(run_id: str) -> Run:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Kein gespeicherter Lauf mit der ID '{run_id}' in {RUNS_DIR}.")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Ältere Läufe enthalten Felder, die es nicht mehr gibt (z. B. "mode").
    return Run(**{key: value for key, value in data.items() if key in Run.__dataclass_fields__})


def open_checkpointer() -> SqliteSaver:
    RUNS_DIR.mkdir(exist_ok=True)
    # check_same_thread=False: LangGraph führt Knoten in mehreren Threads aus.
    return SqliteSaver(sqlite3.connect(RUNS_DIR / "checkpoints.sqlite", check_same_thread=False))
