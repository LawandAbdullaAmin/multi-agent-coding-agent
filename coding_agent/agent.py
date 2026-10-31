"""Coding-Agent (Phase 1): ein einzelner Agent mit Werkzeugen.

Ablauf (ReAct-Schleife):
    agent -> tools -> agent -> tools -> ... -> END
Der Agent entscheidet selbst, welche Werkzeuge er in welcher Reihenfolge nutzt.
Er endet, sobald er ohne Werkzeugaufruf antwortet oder MAX_STEPS erreicht ist.
"""

import os
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from coding_agent.tools import make_tools

MAX_STEPS = 30

SYSTEM_PROMPT = """Du bist ein erfahrener Software-Entwickler und arbeitest autonom in einem Code-Repository.

Vorgehen:
1. Verschaffe dir mit list_files einen Überblick und lies die relevanten Dateien.
2. Führe run_tests aus, um den aktuellen Zustand und die Fehler zu sehen.
3. Finde die Ursache jedes Fehlers, bevor du etwas änderst.
4. Ändere den Code mit edit_file gezielt und minimal.
5. Führe die Tests erneut aus. Wiederhole, bis alle Tests grün sind.
6. Antworte zum Schluss ohne Werkzeugaufruf mit einer kurzen Zusammenfassung:
   Ursache, Änderung und Testergebnis.

Regeln:
- Ändere keine Tests, außer die Aufgabe verlangt es ausdrücklich. Die Tests beschreiben das gewünschte Verhalten.
- Lies eine Datei, bevor du sie änderst.
- Nutze write_file nur für neue Dateien. Bestehende Dateien änderst du mit edit_file.
"""


class State(MessagesState):
    steps: int


def build_graph(repo: Path, sandbox: bool = True, checkpointer: BaseCheckpointSaver | None = None):
    tools = make_tools(repo, sandbox)
    llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), temperature=0).bind_tools(tools)

    def agent(state: State) -> State:
        response = llm.invoke([SystemMessage(SYSTEM_PROMPT)] + state["messages"])
        return {"messages": [response], "steps": state.get("steps", 0) + 1}

    def route_after_agent(state: State) -> str:
        if state["messages"][-1].tool_calls and state["steps"] < MAX_STEPS:
            return "tools"
        return END

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    # handle_tool_errors: Fehler eines Werkzeugs gehen als Nachricht an den Agenten zurück,
    # statt den ganzen Lauf abzubrechen. So kann er sich selbst korrigieren.
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
