"""Evaluation des Teams auf dem eigenen Benchmark.

    python -m coding_agent.evaluate                      # alle Aufgaben
    python -m coding_agent.evaluate --tasks roman orders --repeats 3

Für jede Aufgabe aus benchmark/tasks/:
1. Das Team arbeitet ohne Freigabe auf einer Kopie von repo/.
2. Bewertet wird mit den Original-Tests aus repo/ (auch wenn das Team Tests verändert hat)
   plus versteckten Tests aus hidden/, die das Team nie gesehen hat.
3. Gemessen werden Erfolg, Dauer, Tokens und geschätzte Kosten.
"""

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback

from coding_agent.runs import DEFAULT_TASK, PROJECT_DIR, WORKSPACES_DIR, copy_repo, run_config
from coding_agent.team import build_team_graph, model_names
from coding_agent.tools import ensure_sandbox_image, iter_files, make_tools, tests_green

TASKS_DIR = PROJECT_DIR / "benchmark" / "tasks"
RESULTS_DIR = PROJECT_DIR / "benchmark" / "results"
EVAL_DIR = WORKSPACES_DIR / "eval"

# US-Dollar pro 1 Mio. Tokens (Eingabe, Ausgabe) laut OpenAI-Preisliste. Rabatte für
# gecachte Eingaben sind nicht berücksichtigt, die Kosten sind also eher zu hoch geschätzt.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1-nano": (0.10, 0.40), "gpt-4.1": (2.00, 8.00)}


@dataclass
class Task:
    name: str
    path: Path
    description: str
    difficulty: str
    kind: str
    allow_test_changes: bool  # z. B. wenn die Aufgabe verlangt, Tests zu ergänzen


@dataclass
class Result:
    task: str
    difficulty: str
    repeat: int
    passed: bool
    tests_modified: bool
    seconds: float
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    error: str = ""


def load_tasks(names: list[str] | None = None) -> list[Task]:
    tasks = []
    for path in sorted(p for p in TASKS_DIR.iterdir() if p.is_dir()):
        if names and path.name not in names:
            continue
        meta = json.loads((path / "task.json").read_text(encoding="utf-8"))
        tasks.append(Task(path.name, path, meta.get("task", DEFAULT_TASK), meta["difficulty"], meta["kind"],
                          meta.get("allow_test_changes", False)))
    return tasks


def find_test_files(folder: Path) -> list[Path]:
    return [p.relative_to(folder) for p in iter_files(folder) if p.name.startswith("test_")]


def grade(task: Task, workspace: Path, grading_dir: Path, sandbox: bool = True) -> tuple[bool, bool, str]:
    """Bewertet einen Workspace. Gibt (bestanden, Tests verändert, Testausgabe) zurück."""
    repo = task.path / "repo"
    originals = find_test_files(repo)
    tests_modified = any(
        not (workspace / rel).exists() or (workspace / rel).read_bytes() != (repo / rel).read_bytes()
        for rel in originals
    )
    copy_repo(workspace, grading_dir)
    for rel in originals:
        shutil.copy2(repo / rel, grading_dir / rel)
    if (task.path / "hidden").exists():
        shutil.copytree(task.path / "hidden", grading_dir, dirs_exist_ok=True)
    run_tests = {t.name: t for t in make_tools(grading_dir, sandbox)}["run_tests"]
    output = run_tests.invoke({})
    return tests_green(output), tests_modified, output


def estimate_cost(usage: dict) -> float | None:
    """Kosten in US-Dollar aus den Token-Zahlen je Modell, None bei unbekanntem Modell."""
    total = 0.0
    for model, tokens in usage.items():
        prefix = max((p for p in PRICES if model.startswith(p)), key=len, default=None)
        if prefix is None:
            return None
        price_in, price_out = PRICES[prefix]
        total += (tokens["input_tokens"] * price_in + tokens["output_tokens"] * price_out) / 1_000_000
    return total


def run_one(task: Task, repeat: int, run_dir: Path, sandbox: bool) -> Result:
    name = f"{task.name}-{repeat}"
    workspace = run_dir / name
    copy_repo(task.path / "repo", workspace)
    config = run_config(name, f"eval {task.name}", ["eval"], {"task": task.name, "repeat": repeat})

    error = ""
    start = time.perf_counter()
    with get_usage_metadata_callback() as usage_callback:
        try:
            build_team_graph(workspace, sandbox, human_review=False).invoke({"task": task.description}, config)
        except Exception as e:  # Ein abgestürzter Lauf zählt als nicht gelöst, die Evaluation läuft weiter.
            error = f"{type(e).__name__}: {e}"
    seconds = time.perf_counter() - start

    passed, tests_modified, _ = grade(task, workspace, run_dir / f"{name}-grading", sandbox)
    usage = usage_callback.usage_metadata
    return Result(
        task=task.name, difficulty=task.difficulty, repeat=repeat,
        passed=passed and not error, tests_modified=tests_modified and not task.allow_test_changes,
        seconds=round(seconds, 1),
        input_tokens=sum(u["input_tokens"] for u in usage.values()),
        output_tokens=sum(u["output_tokens"] for u in usage.values()),
        cost_usd=estimate_cost(usage), error=error,
    )


def summarize(results: list[Result], tasks: list[Task]) -> str:
    solved = sum(r.passed for r in results)
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    cost = f"${sum(costs) / len(costs):.4f}" if costs else "?"
    lines = ["| Gelöst | Ø Dauer | Ø Tokens | Ø Kosten | Tests verändert |", "|---|---|---|---|---|",
             f"| {solved}/{len(results)} ({100 * solved / len(results):.0f} %) "
             f"| {sum(r.seconds for r in results) / len(results):.0f} s "
             f"| {sum(r.input_tokens + r.output_tokens for r in results) // len(results):,} "
             f"| {cost} | {sum(r.tests_modified for r in results)} |"]

    lines += ["", "| Aufgabe | Schwierigkeit | Art | Gelöst |", "|---|---|---|---|"]
    for task in tasks:
        rs = [r for r in results if r.task == task.name]
        ok = sum(r.passed for r in rs)
        mark = "✅" if ok == len(rs) else "❌" if ok == 0 else "⚠️"
        lines.append(f"| {task.name} | {task.difficulty} | {task.kind} | {mark} {ok}/{len(rs)} |")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()

    parser = argparse.ArgumentParser(description="Evaluation des Coding-Agenten")
    parser.add_argument("--tasks", nargs="+", help="Nur diese Aufgaben (Ordnernamen in benchmark/tasks)")
    parser.add_argument("--repeats", type=int, default=1, help="Läufe pro Aufgabe")
    parser.add_argument("--workers", type=int, default=4, help="Parallele Läufe")
    parser.add_argument("--no-sandbox", action="store_true", help="Tests lokal statt im Docker-Container")
    args = parser.parse_args()

    sandbox = not args.no_sandbox
    if sandbox:
        ensure_sandbox_image()
    tasks = load_tasks(args.tasks)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = EVAL_DIR / stamp
    jobs = [(task, repeat) for task in tasks for repeat in range(1, args.repeats + 1)]
    print(f"{len(tasks)} Aufgaben x {args.repeats} Wiederholungen = {len(jobs)} Läufe\n")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, task, repeat, run_dir, sandbox) for task, repeat in jobs]
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            status = "✅" if r.passed else "❌"
            note = (" (Tests verändert)" if r.tests_modified else "") + (f" [{r.error[:80]}]" if r.error else "")
            print(f"[{len(results):>2}/{len(jobs)}] {status} {r.task:<14} {r.seconds:>5.0f} s{note}")

    results.sort(key=lambda r: (r.task, r.repeat))
    report = summarize(results, tasks)
    models = model_names()
    header = (f"# Evaluation {stamp}\n\nModelle: günstig `{models['fast']}`, stark `{models['strong']}`, "
              f"Wiederholungen: {args.repeats}\n\n")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{stamp}.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS_DIR / f"{stamp}.md").write_text(header + report + "\n", encoding="utf-8")
    print("\n" + report + f"\n\nGespeichert in {RESULTS_DIR / stamp}.md/.json")


if __name__ == "__main__":
    main()
