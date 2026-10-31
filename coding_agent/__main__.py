"""Kommandozeile: python -m coding_agent --repo <ordner> "<aufgabe>"

Standardmäßig arbeitet das Team (Supervisor mit Fach-Agenten) auf einer Kopie
des Repositorys im Ordner workspaces/ und zeigt am Ende die Änderungen als Diff.
Mit --mode single läuft stattdessen der einzelne Agent aus Phase 1,
mit --in-place wird das Repository direkt geändert.
"""

import argparse
import difflib
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coding_agent.agent import MAX_STEPS, build_graph
from coding_agent.team import build_team_graph
from coding_agent.tools import IGNORED_DIRS, ensure_sandbox_image, iter_files, read_text

WORKSPACES_DIR = Path(__file__).resolve().parent.parent / "workspaces"
DEFAULT_TASK = "Finde und behebe die Fehler, sodass alle Tests erfolgreich durchlaufen."
PREVIEW_CHARS = 400


def prepare_workspace(repo: Path, in_place: bool) -> Path:
    if in_place:
        return repo
    workspace = WORKSPACES_DIR / f"{repo.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    return workspace


def show_diff(original: Path, workspace: Path) -> None:
    changed = False
    for file in iter_files(workspace):
        rel = file.relative_to(workspace)
        before = original / rel
        old = read_text(before).splitlines(keepends=True) if before.exists() else []
        new = read_text(file).splitlines(keepends=True)
        diff = list(difflib.unified_diff(old, new, f"a/{rel.as_posix()}", f"b/{rel.as_posix()}"))
        if diff:
            changed = True
            sys.stdout.writelines(diff)
    if not changed:
        print("(keine Änderungen)")


def print_update(update: dict) -> None:
    for message in update.get("messages") or []:
        if isinstance(message, AIMessage):
            if message.content:
                print(f"\n[Agent] {message.content}")
            for call in message.tool_calls:
                args = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in call["args"].items())
                print(f"  -> {call['name']}({args})")
        elif isinstance(message, ToolMessage):
            preview = message.content[:PREVIEW_CHARS].replace("\n", "\n     ")
            print(f"     {preview}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()

    parser = argparse.ArgumentParser(description="Autonomer Coding-Agent mit LangGraph")
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK, help="Aufgabe für den Agenten")
    parser.add_argument("--repo", type=Path, required=True, help="Ordner des Repositorys")
    parser.add_argument("--mode", choices=["team", "single"], default="team",
                        help="team: Supervisor mit Fach-Agenten, single: ein einzelner Agent")
    parser.add_argument("--in-place", action="store_true", help="Repository direkt ändern statt einer Kopie")
    parser.add_argument("--no-sandbox", action="store_true", help="Tests lokal statt im Docker-Container ausführen")
    args = parser.parse_args()

    sandbox = not args.no_sandbox
    if sandbox:
        try:
            ensure_sandbox_image()
        except RuntimeError as e:
            sys.exit(f"Fehler: {e}")

    repo = args.repo.resolve()
    workspace = prepare_workspace(repo, args.in_place)
    print(f"Aufgabe:   {args.task}\nWorkspace: {workspace}\n"
          f"Modus:     {args.mode}\nSandbox:   {'Docker' if sandbox else 'aus (lokal)'}")

    if args.mode == "team":
        app = build_team_graph(workspace, sandbox)
        inputs = {"task": args.task}
    else:
        app = build_graph(workspace, sandbox)
        inputs = {"messages": [HumanMessage(args.task)], "steps": 0}

    state = {}
    # subgraphs=True: auch die Schritte innerhalb der Fach-Agenten live anzeigen
    for namespace, chunk in app.stream(
        # Die eigentlichen Limits sind MAX_STEPS, MAX_ROUNDS und WORKER_MODEL_CALLS.
        # recursion_limit ist nur ein Sicherheitsnetz von LangGraph.
        inputs, {"recursion_limit": 200}, stream_mode="updates", subgraphs=True,
    ):
        for node, update in chunk.items():
            if not isinstance(update, dict):
                continue
            if node == "supervisor":
                target = update["next"]
                print(f"\n[Supervisor] -> {target}" + (f": {update['instruction']}" if target != "finish" else ""))
            else:
                print_update(update)
            if not namespace:
                state.update(update)

    if args.mode == "team":
        passed = {True: "ja", False: "nein"}.get(state.get("tests_passed"), "unbekannt")
        print(f"\n=== Ergebnis ===\n{state.get('summary', '')}\nTests bestanden: {passed}")
    elif state.get("steps", 0) >= MAX_STEPS:
        print(f"\nAbgebrochen: Schrittlimit ({MAX_STEPS}) erreicht.")
    if not args.in_place:
        print("\n=== Änderungen ===")
        show_diff(repo, workspace)


if __name__ == "__main__":
    main()
