"""Coding-Agent (Phase 2b): Supervisor mit Fach-Agenten.

Ablauf:
    supervisor -> explorer | developer | tester -> supervisor -> ... -> END

Der Supervisor ist ein eigener LangGraph-Knoten. Er entscheidet per strukturierter
Ausgabe, welcher Fach-Agent als Nächstes arbeitet und mit welchem Auftrag.
Die Fach-Agenten sind mit create_agent gebaut und bekommen nur die Werkzeuge,
die sie für ihre Rolle brauchen (z. B. darf nur der Entwickler Code ändern).
"""

import operator
import os
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from coding_agent.tools import make_tools

MAX_ROUNDS = 12
WORKER_MODEL_CALLS = 15

WORKER_RULES = ("\n\nDu arbeitest autonom in einem automatisierten Ablauf. Niemand beantwortet Rückfragen: "
                "stelle keine Fragen, sondern erledige deinen Auftrag vollständig und berichte dann.")

SPECIALISTS = {
    "explorer": (
        ["list_files", "read_file", "search_code"],
        "Du bist der Code-Explorer im Team. Du änderst nichts. Untersuche das Repository und berichte knapp: "
        "relevante Dateien, die Ursache jedes Fehlers mit Zeilennummern und was genau geändert werden muss.",
    ),
    "developer": (
        ["read_file", "search_code", "edit_file", "write_file"],
        "Du bist der Entwickler im Team. Setze den Auftrag mit gezielten, minimalen Änderungen um. "
        "Lies eine Datei, bevor du sie änderst, und nutze edit_file für bestehende Dateien. "
        "Ändere keine Tests, außer der Auftrag verlangt es ausdrücklich. Berichte zum Schluss, was du geändert hast.",
    ),
    "tester": (
        ["run_tests", "read_file"],
        "Du bist der Tester im Team. Du änderst nichts. Führe die Tests aus und berichte, wie viele "
        "bestanden haben und wie viele fehlgeschlagen sind, und bei Fehlern die genaue Ursache laut Ausgabe.",
    ),
}

SUPERVISOR_PROMPT = """Du bist der Supervisor eines Entwickler-Teams und steuerst die Arbeit an einer Aufgabe.

Dein Team:
- explorer: liest und durchsucht den Code, findet Fehlerursachen. Ändert nichts.
- developer: ändert den Code.
- tester: führt die Tests aus und berichtet das Ergebnis. Ändert nichts.

Entscheide jeweils, wer als Nächstes arbeitet, und gib ihm einen klaren, konkreten Auftrag.
Die Fach-Agenten sehen nur die Aufgabe und deinen Auftrag, nicht die bisherigen Berichte.
Gib ihnen deshalb alle nötigen Informationen daraus mit (Dateien, Zeilen, Ursachen).
Typischer Ablauf: explorer -> developer -> tester, bei Fehlern zurück zum developer.
Wähle finish erst, wenn der tester bestätigt hat, dass alle Tests bestehen,
oder wenn die Aufgabe nicht lösbar ist. Fasse dann im Feld summary zusammen, was gemacht wurde."""


class Decision(BaseModel):
    next: Literal["explorer", "developer", "tester", "finish"]
    instruction: str = Field(description="Konkreter Auftrag an den Fach-Agenten, leer bei finish")
    summary: str = Field(description="Abschlussbericht bei finish, sonst leer")


class Report(TypedDict):
    agent: str
    instruction: str
    result: str


class State(TypedDict, total=False):
    task: str
    reports: Annotated[list[Report], operator.add]
    next: str
    instruction: str
    summary: str
    rounds: int
    tests_passed: bool


def format_reports(reports: list[Report]) -> str:
    if not reports:
        return "(noch keine)"
    return "\n\n".join(f"[{r['agent']}] Auftrag: {r['instruction']}\nBericht: {r['result']}" for r in reports)


def last_test_result(messages: list) -> bool | None:
    """Wertet die Werkzeugaufrufe aus: Haben die Tests zuletzt bestanden?

    None, wenn der Agent weder Tests ausgeführt noch Code geändert hat.
    """
    passed = None
    for message in messages:
        if isinstance(message, ToolMessage):
            if message.name == "run_tests":
                passed = message.content.startswith("Exit-Code: 0")
            elif message.name in ("edit_file", "write_file"):
                passed = False
    return passed


def build_team_graph(repo: Path, sandbox: bool = True):
    model = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), temperature=0)
    tools = {t.name: t for t in make_tools(repo, sandbox)}
    supervisor_llm = model.with_structured_output(Decision)

    def supervisor(state: State) -> State:
        rounds = state.get("rounds", 0)
        if rounds >= MAX_ROUNDS:
            return {"next": "finish", "summary": f"Abgebrochen: Rundenlimit ({MAX_ROUNDS}) erreicht."}
        decision = supervisor_llm.invoke([
            SystemMessage(SUPERVISOR_PROMPT),
            HumanMessage(f"Aufgabe: {state['task']}\n\nBisherige Berichte:\n{format_reports(state.get('reports', []))}"),
        ])
        return {
            "next": decision.next,
            "instruction": decision.instruction,
            "summary": decision.summary,
            "rounds": rounds + 1,
        }

    def make_worker(name: str, tool_names: list[str], prompt: str):
        agent = create_agent(
            model,
            [tools[n] for n in tool_names],
            system_prompt=prompt + WORKER_RULES,
            middleware=[ModelCallLimitMiddleware(run_limit=WORKER_MODEL_CALLS)],
            name=name,
        )

        def worker(state: State) -> State:
            result = agent.invoke({"messages": [HumanMessage(
                f"Aufgabe des Teams: {state['task']}\n\nDein Auftrag: {state['instruction']}"
            )]})
            messages = result["messages"]
            update: State = {"reports": [{
                "agent": name,
                "instruction": state["instruction"],
                "result": messages[-1].text or "(kein Bericht)",
            }]}
            passed = last_test_result(messages)
            if passed is not None:
                update["tests_passed"] = passed
            return update

        return worker

    def route_after_supervisor(state: State) -> str:
        return END if state["next"] == "finish" else state["next"]

    graph = StateGraph(State)
    graph.add_node("supervisor", supervisor)
    for name, (tool_names, prompt) in SPECIALISTS.items():
        graph.add_node(name, make_worker(name, tool_names, prompt))
        graph.add_edge(name, "supervisor")

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor, [*SPECIALISTS, END])
    return graph.compile()
