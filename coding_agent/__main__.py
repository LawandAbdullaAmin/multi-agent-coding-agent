"""Command line: python -m coding_agent --repo <folder> "<task>"

The team (supervisor with specialist agents) works on a copy of the repository
in the workspaces/ folder. At the end it shows the changes as a diff and asks for
approval: only then are they applied to the repository.
With --in-place the repository is changed directly (without approval).
Every run is saved and can be continued with --resume <run-id>.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from coding_agent.runs import (
    DEFAULT_TASK,
    apply_changes,
    diff_text,
    load_run,
    new_run,
    open_checkpointer,
    run_config,
    save_run,
)
from coding_agent.team import ReviewAnswer, build_team_graph
from coding_agent.tools import ensure_sandbox_image

PREVIEW_CHARS = 400
YES = {"", "y", "yes"}
NO = {"n", "no"}


def show_diff(original: Path, workspace: Path) -> None:
    print(diff_text(original, workspace) or "(no changes)")


def parse_review_answer(text: str) -> ReviewAnswer:
    # ﻿: byte order mark that Windows PowerShell prepends when piping input
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
    """Runs the graph until it finishes or pauses at an interrupt."""
    # subgraphs=True: also show the steps inside the specialist agents live
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

    parser = argparse.ArgumentParser(description="Autonomous coding agent built with LangGraph")
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK, help="Task for the agent")
    parser.add_argument("--repo", type=Path, help="Folder of the repository")
    parser.add_argument("--resume", metavar="RUN_ID", help="Continue a saved run")
    parser.add_argument("--in-place", action="store_true", help="Change the repository directly instead of a copy")
    parser.add_argument("--auto-approve", action="store_true", help="Finish without human approval")
    parser.add_argument("--no-sandbox", action="store_true", help="Run tests locally instead of in the Docker container")
    args = parser.parse_args()
    if bool(args.repo) == bool(args.resume):
        parser.error("Specify either --repo (new run) or --resume (continue a run).")

    try:
        run_info = load_run(args.resume) if args.resume else new_run(
            args.repo, args.task, args.in_place, args.auto_approve, not args.no_sandbox)
    except FileNotFoundError as e:
        sys.exit(f"Error: {e}")
    if run_info.sandbox:
        try:
            ensure_sandbox_image()
        except RuntimeError as e:
            sys.exit(f"Error: {e}")
    save_run(run_info)

    repo, workspace = Path(run_info.repo), Path(run_info.workspace)
    resume_hint = f"python -m coding_agent --resume {run_info.id}"
    print(f"Run ID:    {run_info.id}\nTask:      {run_info.task}\nWorkspace: {workspace}\n"
          f"Sandbox:   {'Docker' if run_info.sandbox else 'off (local)'}\n"
          f"Approval:  {'yes' if run_info.human_review else 'no'}")

    app = build_team_graph(workspace, run_info.sandbox, run_info.human_review, open_checkpointer())
    inputs = {"task": run_info.task}

    config = run_config(run_info.id, "coding-agent", ["cli"],
                        {"run_id": run_info.id, "task": run_info.task, "repo": repo.name})
    snapshot = app.get_state(config)
    state = dict(snapshot.values)

    try:
        if not args.resume:
            run(app, inputs, config, state)
        elif not snapshot.next:
            print("\nThis run is already finished.")
            return
        elif not snapshot.interrupts:
            print("\nContinuing the run from the last saved step ...")
            run(app, None, config, state)  # None: continue from the last checkpoint

        while run_info.human_review and app.get_state(config).interrupts:
            passed = {True: "yes", False: "no"}.get(state.get("tests_passed"), "unknown")
            print(f"\n=== Result ===\n{state.get('summary', '')}\nTests passed: {passed}")
            print("\n=== Changes ===")
            show_diff(repo, workspace)
            answer = parse_review_answer(input("\nApply? [Y]es / [n]o / or type feedback: "))
            run(app, Command(resume=answer), config, state)
    except (KeyboardInterrupt, EOFError):
        sys.exit(f"\n\nPaused. Progress has been saved. Continue with:\n  {resume_hint}")

    if run_info.in_place:
        return
    if run_info.human_review:
        if state.get("review") == "approve":
            files = apply_changes(repo, workspace)
            print(f"\nApplied to {repo}: " + (", ".join(f.as_posix() for f in files) or "(no changes)"))
        else:
            print(f"\nDiscarded. {repo} is unchanged, the working copy is in {workspace}.")
    else:
        print("\n=== Changes ===")
        show_diff(repo, workspace)


if __name__ == "__main__":
    main()
