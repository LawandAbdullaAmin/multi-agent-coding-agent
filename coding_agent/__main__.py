"""Kommandozeile: python -m coding_agent --repo <ordner> "<aufgabe>"

Standardmäßig arbeitet das Team (Supervisor mit Fach-Agenten) auf einer Kopie
des Repositorys im Ordner workspaces/. Am Ende zeigt es die Änderungen als Diff
und fragt nach einer Freigabe: Erst dann werden sie ins Repository übernommen.
Mit --mode single läuft stattdessen der einzelne Agent aus Phase 1,
mit --in-place wird das Repository direkt geändert (ohne Freigabe).
"""

import argparse
import difflib
import shutil
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from coding_agent.agent import MAX_STEPS, build_graph
from coding_agent.team import ReviewAnswer, build_team_graph
from coding_agent.tools import IGNORED_DIRS, ensure_sandbox_image, iter_files, read_text

WORKSPACES_DIR = Path(__file__).resolve().parent.parent / "workspaces"
DEFAULT_TASK = "Finde und behebe die Fehler, sodass alle Tests erfolgreich durchlaufen."
PREVIEW_CHARS = 400
YES = {"", "j", "ja", "y", "yes"}
NO = {"n", "nein", "no"}


def prepare_workspace(repo: Path, in_place: bool) -> Path:
    if in_place:
        return repo
    workspace = WORKSPACES_DIR / f"{repo.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    return workspace


def changed_files(original: Path, workspace: Path) -> list[Path]:
    """Relative Pfade aller Dateien, die im Workspace neu oder geändert sind."""
    changed = []
    for file in iter_files(workspace):
        rel = file.relative_to(workspace)
        before = original / rel
        if not before.exists() or before.read_bytes() != file.read_bytes():
            changed.append(rel)
    return changed


def show_diff(original: Path, workspace: Path) -> None:
    files = changed_files(original, workspace)
    for rel in files:
        before = original / rel
        old = read_text(before).splitlines(keepends=True) if before.exists() else []
        new = read_text(workspace / rel).splitlines(keepends=True)
        sys.stdout.writelines(difflib.unified_diff(old, new, f"a/{rel.as_posix()}", f"b/{rel.as_posix()}"))
    if not files:
        print("(keine Änderungen)")


def apply_changes(original: Path, workspace: Path) -> list[Path]:
    files = changed_files(original, workspace)
    for rel in files:
        target = original / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace / rel, target)
    return files


def parse_review_answer(text: str) -> ReviewAnswer:
    text = text.strip()
    if text.lower() in YES:
        return {"action": "approve"}
    if text.lower() in NO:
        return {"action": "reject"}
    return {"action": "feedback", "feedback": text}


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


def run(app, inputs, config: dict, state: dict) -> None:
    """Führt den Graphen aus, bis er fertig ist oder an einem interrupt pausiert."""
    # subgraphs=True: auch die Schritte innerhalb der Fach-Agenten live anzeigen
    for namespace, chunk in app.stream(inputs, config, stream_mode="updates", subgraphs=True):
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


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()

    parser = argparse.ArgumentParser(description="Autonomer Coding-Agent mit LangGraph")
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK, help="Aufgabe für den Agenten")
    parser.add_argument("--repo", type=Path, required=True, help="Ordner des Repositorys")
    parser.add_argument("--mode", choices=["team", "single"], default="team",
                        help="team: Supervisor mit Fach-Agenten, single: ein einzelner Agent")
    parser.add_argument("--in-place", action="store_true", help="Repository direkt ändern statt einer Kopie")
    parser.add_argument("--auto-approve", action="store_true", help="Ohne Freigabe durch einen Menschen beenden")
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
    # Freigabe nur, wenn auf einer Kopie gearbeitet wird: Nur dann kann man Änderungen noch verwerfen.
    human_review = args.mode == "team" and not args.auto_approve and not args.in_place
    print(f"Aufgabe:   {args.task}\nWorkspace: {workspace}\nModus:     {args.mode}\n"
          f"Sandbox:   {'Docker' if sandbox else 'aus (lokal)'}\nFreigabe:  {'ja' if human_review else 'nein'}")

    if args.mode == "team":
        app = build_team_graph(workspace, sandbox, human_review)
        inputs = {"task": args.task}
    else:
        app = build_graph(workspace, sandbox)
        inputs = {"messages": [HumanMessage(args.task)], "steps": 0}

    # thread_id: unter dieser Kennung speichert der Checkpointer den Zustand dieses Laufs.
    # Die eigentlichen Limits sind MAX_STEPS, MAX_ROUNDS und WORKER_MODEL_CALLS;
    # recursion_limit ist nur ein Sicherheitsnetz von LangGraph.
    config = {"recursion_limit": 200, "configurable": {"thread_id": str(uuid.uuid4())}}
    state = {}
    run(app, inputs, config, state)

    while human_review and app.get_state(config).interrupts:
        passed = {True: "ja", False: "nein"}.get(state.get("tests_passed"), "unbekannt")
        print(f"\n=== Ergebnis ===\n{state.get('summary', '')}\nTests bestanden: {passed}")
        print("\n=== Änderungen ===")
        show_diff(repo, workspace)
        answer = parse_review_answer(input("\nÜbernehmen? [J]a / [n]ein / oder Feedback eingeben: "))
        run(app, Command(resume=answer), config, state)

    if args.mode == "single" and state.get("steps", 0) >= MAX_STEPS:
        print(f"\nAbgebrochen: Schrittlimit ({MAX_STEPS}) erreicht.")

    if args.in_place:
        return
    if human_review:
        if state.get("review") == "approve":
            files = apply_changes(repo, workspace)
            print(f"\nÜbernommen in {repo}: " + (", ".join(f.as_posix() for f in files) or "(keine Änderungen)"))
        else:
            print(f"\nVerworfen. {repo} bleibt unverändert, die Arbeitskopie liegt in {workspace}.")
    else:
        print("\n=== Änderungen ===")
        show_diff(repo, workspace)


if __name__ == "__main__":
    main()
