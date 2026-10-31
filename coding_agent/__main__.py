"""Kommandozeile: python -m coding_agent --repo <ordner> "<aufgabe>"

Das Team (Supervisor mit Fach-Agenten) arbeitet auf einer Kopie des Repositorys
im Ordner workspaces/. Am Ende zeigt es die Änderungen als Diff und fragt nach einer
Freigabe: Erst dann werden sie ins Repository übernommen.
Mit --in-place wird das Repository direkt geändert (ohne Freigabe).
Jeder Lauf wird gespeichert und kann mit --resume <lauf-id> fortgesetzt werden.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from coding_agent.runs import apply_changes, diff_text, load_run, new_run, open_checkpointer, save_run
from coding_agent.team import ReviewAnswer, build_team_graph
from coding_agent.tools import ensure_sandbox_image

DEFAULT_TASK = "Finde und behebe die Fehler, sodass alle Tests erfolgreich durchlaufen."
PREVIEW_CHARS = 400
YES = {"", "j", "ja", "y", "yes"}
NO = {"n", "nein", "no"}


def show_diff(original: Path, workspace: Path) -> None:
    print(diff_text(original, workspace) or "(keine Änderungen)")


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
    parser.add_argument("--in-place", action="store_true", help="Repository direkt ändern statt einer Kopie")
    parser.add_argument("--auto-approve", action="store_true", help="Ohne Freigabe durch einen Menschen beenden")
    parser.add_argument("--no-sandbox", action="store_true", help="Tests lokal statt im Docker-Container ausführen")
    args = parser.parse_args()
    if bool(args.repo) == bool(args.resume):
        parser.error("Gib entweder --repo (neuer Lauf) oder --resume (Lauf fortsetzen) an.")

    try:
        run_info = load_run(args.resume) if args.resume else new_run(
            args.repo, args.task, args.in_place, args.auto_approve, not args.no_sandbox)
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
          f"Sandbox:   {'Docker' if run_info.sandbox else 'aus (lokal)'}\n"
          f"Freigabe:  {'ja' if run_info.human_review else 'nein'}")

    app = build_team_graph(workspace, run_info.sandbox, run_info.human_review, open_checkpointer())
    inputs = {"task": run_info.task}

    # thread_id: unter dieser Kennung speichert der Checkpointer den Zustand dieses Laufs.
    # Die eigentlichen Limits sind MAX_ROUNDS und WORKER_MODEL_CALLS;
    # recursion_limit ist nur ein Sicherheitsnetz von LangGraph.
    # run_name, tags und metadata erscheinen im LangSmith-Trace und machen Läufe dort filterbar.
    config = {
        "recursion_limit": 200,
        "configurable": {"thread_id": run_info.id},
        "run_name": "coding-agent",
        "tags": ["cli"],
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
