"""Runs: create a working copy, save settings and checkpoints, apply changes.

For every run there is a JSON file with its settings in .runs/. LangGraph saves the
graph's intermediate states in .runs/checkpoints.sqlite (thread_id = run ID).
Work happens on a copy of the repository under workspaces/<run-id>.
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
DEFAULT_TASK = "Find and fix the bugs so that all tests pass."


@dataclass
class Run:
    id: str
    task: str
    repo: str
    workspace: str
    sandbox: bool
    human_review: bool
    in_place: bool


def copy_repo(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*IGNORED_DIRS))


def run_config(thread_id: str, run_name: str, tags: list[str], metadata: dict) -> dict:
    """Configuration for one run of the graph.

    thread_id: the checkpointer saves the state under this ID. run_name, tags and
    metadata appear in the LangSmith trace and make runs filterable there. The actual limits
    are MAX_ROUNDS and WORKER_MODEL_CALLS; recursion_limit is only a LangGraph safety net.
    """
    return {"recursion_limit": 200, "configurable": {"thread_id": thread_id},
            "run_name": run_name, "tags": tags, "metadata": metadata}


def new_run(repo: Path, task: str, in_place: bool = False, auto_approve: bool = False, sandbox: bool = True) -> Run:
    repo = repo.resolve()
    run_id = f"{repo.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    workspace = repo if in_place else WORKSPACES_DIR / run_id
    if not in_place:
        copy_repo(repo, workspace)
    return Run(
        id=run_id, task=task, repo=str(repo), workspace=str(workspace), sandbox=sandbox, in_place=in_place,
        # Approval only when working on a copy: only then can changes still be discarded.
        human_review=not auto_approve and not in_place,
    )


def changed_files(original: Path, workspace: Path) -> list[Path]:
    """Relative paths of all files that are new or changed in the workspace."""
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
        raise FileNotFoundError(f"No saved run with the ID '{run_id}' in {RUNS_DIR}.")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Fields that existed in older versions are ignored.
    return Run(**{key: value for key, value in data.items() if key in Run.__dataclass_fields__})


def open_checkpointer() -> SqliteSaver:
    RUNS_DIR.mkdir(exist_ok=True)
    # check_same_thread=False: LangGraph runs nodes in several threads.
    return SqliteSaver(sqlite3.connect(RUNS_DIR / "checkpoints.sqlite", check_same_thread=False))
