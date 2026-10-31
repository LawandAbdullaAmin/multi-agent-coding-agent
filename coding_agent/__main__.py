"""Kommandozeile: python -m coding_agent --repo <ordner> "<aufgabe>"

Standardmäßig arbeitet das Team (Supervisor mit Fach-Agenten) auf einer Kopie
des Repositorys im Ordner workspaces/. Am Ende zeigt es die Änderungen als Diff
und fragt nach einer Freigabe: Erst dann werden sie ins Repository übernommen.
Mit --mode single läuft stattdessen der einzelne Agent aus Phase 1,
mit --in-place wird das Repository direkt geändert (ohne Freigabe).
Jeder Lauf wird gespeichert und kann mit --resume <lauf-id> fortgesetzt werden.
"""

import argparse
import difflib
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from coding_agent.agent import MAX_STEPS, build_graph
from coding_agent.runs import Run, load_run, open_checkpointer, save_run
from coding_agent.team import ReviewAnswer, build_team_graph
from coding_agent.tools import IGNORED_DIRS, ensure_sandbox_image, iter_files, read_text

WORKSPACES_DIR = Path(__file__).resolve().parent.parent / "workspaces"
DEFAULT_TASK = "Finde und behebe die Fehler, sodass alle Tests erfolgreich durchlaufen."
PREVIEW_CHARS = 400
YES = {"", "j", "ja", "y", "yes"}
NO = {"n", "nein", "no"}


def new_run(args: argparse.Namespace) -> Run:
    repo = args.repo.resolve()
    run_id = f"{repo.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    workspace = repo if args.in_place else WORKSPACES_DIR / run_id
    if not args.in_place:
        shutil.copytree(repo, workspace, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    return Run(
        id=run_id, task=args.task, repo=str(repo), workspace=str(workspace), mode=args.mode,
        sandbox=not args.no_sandbox, in_place=args.in_place,
        # Freigabe nur, wenn auf einer Kopie gearbeitet wird: Nur dann kann man Änderungen noch verwerfen.
        human_review=args.mode == "team" and not args.auto_approve and not args.in_place,
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
    # ﻿: Byte-Order-Mark, das Windows PowerShell beim Weiterleiten (Pipe) voranstellt
    text = text.replace("﻿", "").strip()
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
    parser.add_argument("--repo", type=Path, help="Ordner des Repositorys")
    parser.add_argument("--resume", metavar="LAUF_ID", help="Einen gespeicherten Lauf fortsetzen")
    parser.add_argument("--mode", choices=["team", "single"], default="team",
                        help="team: Supervisor mit Fach-Agenten, single: ein einzelner Agent")
    parser.add_argument("--in-place", action="store_true", help="Repository direkt ändern statt einer Kopie")
    parser.add_argument("--auto-approve", action="store_true", help="Ohne Freigabe durch einen Menschen beenden")
    parser.add_argument("--no-sandbox", action="store_true", help="Tests lokal statt im Docker-Container ausführen")
    args = parser.parse_args()
    if bool(args.repo) == bool(args.resume):
        parser.error("Gib entweder --repo (neuer Lauf) oder --resume (Lauf fortsetzen) an.")

    try:
        run_info = load_run(args.resume) if args.resume else new_run(args)
    except FileNotFoundError as e:
        sys.exit(f"Fehler: {e}")
    if run_info.sandbox:
        try:
            ensure_sandbox_image()
        except RuntimeError as e:
            sys.exit(f"Fehler: {e}")
    save_run(run_info)

    repo, workspace = Path(run_info.repo), Path(run_info.workspace)
    resume_hint = f"python -m coding_agent --resume {run_info.id}"
    print(f"Lauf-ID:   {run_info.id}\nAufgabe:   {run_info.task}\nWorkspace: {workspace}\n"
          f"Modus:     {run_info.mode}\nSandbox:   {'Docker' if run_info.sandbox else 'aus (lokal)'}\n"
          f"Freigabe:  {'ja' if run_info.human_review else 'nein'}")

    checkpointer = open_checkpointer()
    if run_info.mode == "team":
        app = build_team_graph(workspace, run_info.sandbox, run_info.human_review, checkpointer)
        inputs = {"task": run_info.task}
    else:
        app = build_graph(workspace, run_info.sandbox, checkpointer)
        inputs = {"messages": [HumanMessage(run_info.task)], "steps": 0}

    # thread_id: unter dieser Kennung speichert der Checkpointer den Zustand dieses Laufs.
    # Die eigentlichen Limits sind MAX_STEPS, MAX_ROUNDS und WORKER_MODEL_CALLS;
    # recursion_limit ist nur ein Sicherheitsnetz von LangGraph.
    # run_name, tags und metadata erscheinen im LangSmith-Trace und machen Läufe dort filterbar.
    config = {
        "recursion_limit": 200,
        "configurable": {"thread_id": run_info.id},
        "run_name": f"coding-agent ({run_info.mode})",
        "tags": [run_info.mode],
        "metadata": {"lauf_id": run_info.id, "task": run_info.task, "repo": Path(run_info.repo).name},
    }
    snapshot = app.get_state(config)
    state = dict(snapshot.values)

    try:
        if not args.resume:
            run(app, inputs, config, state)
        elif not snapshot.next:
            print("\nDieser Lauf ist bereits abgeschlossen.")
            return
        elif not snapshot.interrupts:
            print("\nSetze den Lauf am letzten gespeicherten Schritt fort ...")
            run(app, None, config, state)  # None: ab dem letzten Checkpoint weiterlaufen

        while run_info.human_review and app.get_state(config).interrupts:
            passed = {True: "ja", False: "nein"}.get(state.get("tests_passed"), "unbekannt")
            print(f"\n=== Ergebnis ===\n{state.get('summary', '')}\nTests bestanden: {passed}")
            print("\n=== Änderungen ===")
            show_diff(repo, workspace)
            answer = parse_review_answer(input("\nÜbernehmen? [J]a / [n]ein / oder Feedback eingeben: "))
            run(app, Command(resume=answer), config, state)
    except (KeyboardInterrupt, EOFError):
        sys.exit(f"\n\nPausiert. Der Zwischenstand ist gespeichert. Fortsetzen mit:\n  {resume_hint}")

    if run_info.mode == "single" and state.get("steps", 0) >= MAX_STEPS:
        print(f"\nAbgebrochen: Schrittlimit ({MAX_STEPS}) erreicht.")

    if run_info.in_place:
        return
    if run_info.human_review:
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
