"""Coding-Agent: Supervisor mit Fach-Agenten und menschlicher Freigabe.

Ablauf:
    supervisor -> explorer | test_writer | developer | tester | reviewer -> supervisor -> ... -> review -> END
                                                                                                 |
                                                             Feedback des Menschen -> supervisor <+

Der Supervisor ist ein eigener LangGraph-Knoten. Er entscheidet per strukturierter
Ausgabe, welcher Fach-Agent als Nächstes arbeitet und mit welchem Auftrag.
Die Fach-Agenten sind mit create_agent gebaut. Ihre Rechte werden im Code durchgesetzt:
Nur der Entwickler ändert Produktivcode, nur der Test-Autor legt neue Tests an,
bestehende Tests sind für alle schreibgeschützt.
Abschließen kann der Supervisor erst, wenn die Tests bestehen und der Reviewer die
Lösung gegen die Anforderung freigegeben hat (verifiziert).
Rollen, die urteilen müssen, nutzen ein starkes Modell, Routinerollen ein günstiges.
Der Entwickler startet günstig und wechselt zum starken Modell, sobald er nachbessern muss.
Im Knoten review pausiert der Graph (interrupt), bis ein Mensch das Ergebnis
freigibt, verwirft oder Feedback gibt.
"""

import operator
import os
from pathlib import Path
from typing import Annotated, Literal, NamedTuple, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from coding_agent.tools import WritePolicy, is_test_file, iter_files, make_tools

MAX_ROUNDS = 15
WORKER_MODEL_CALLS = 15

WORKER_RULES = ("\n\nDu arbeitest autonom in einem automatisierten Ablauf. Niemand beantwortet Rückfragen: "
                "stelle keine Fragen, sondern erledige deinen Auftrag vollständig und berichte dann.")

READ_TOOLS = ["list_files", "read_file", "search_code"]

ModelTier = Literal["fast", "strong", "escalate"]


class Role(NamedTuple):
    tools: list[str]
    toolset: str      # Werkzeugsatz mit den Schreibrechten der Rolle, siehe write_policies
    model: ModelTier  # escalate: günstig beim ersten Einsatz, stark bei jedem weiteren
    prompt: str


def model_names() -> dict[str, str]:
    return {"fast": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "strong": os.getenv("OPENAI_STRONG_MODEL", "gpt-4.1")}


def make_model(name: str) -> ChatOpenAI:
    # Reasoning-Modelle (gpt-5, o3, ...) unterstützen keine temperature.
    return ChatOpenAI(model=name, temperature=0) if name.startswith("gpt-4") else ChatOpenAI(model=name)


SPECIALISTS = {
    "explorer": Role(
        READ_TOOLS, "read_only", "fast",
        "Du bist der Code-Explorer im Team. Du änderst nichts. Untersuche das Repository und berichte knapp: "
        "relevante Dateien, die Ursache jedes Fehlers mit Zeilennummern und was genau geändert werden muss. "
        "Prüfe auch, ob der Code alles erfüllt, was Docstrings und Kommentare versprechen, "
        "auch wenn kein Test es prüft (z. B. beschriebene Fehlerfälle).",
    ),
    "test_writer": Role(
        [*READ_TOOLS, "write_file", "edit_file", "run_tests"], "new_tests", "strong",
        "Du bist der Test-Autor im Team. Bevor der Code geändert wird, schreibst du Tests, die das gewünschte "
        "Verhalten vollständig beschreiben: aus der Aufgabe, aus Docstrings und Kommentaren und aus dem Auftrag. "
        "Denke besonders an Grenz- und Fehlerfälle, die beschrieben, aber noch nicht getestet sind. "
        "Lege die Tests in einer neuen Datei an, z. B. test_spec_<modul>.py. Bestehende Testdateien und "
        "Produktivcode darfst du nicht ändern. Teste nur, was ausdrücklich verlangt oder dokumentiert ist: "
        "Schreibe über jeden Test einen Kommentar mit dem wörtlichen Zitat aus Aufgabe oder Docstring, das ihn "
        "begründet. Ohne solches Zitat schreibst du den Test nicht. Triff keine eigenen Annahmen über Formate, "
        "Grenzen, Wertebereiche oder zusätzliche Fehlerfälle. Wenig korrekte Tests sind besser als viele erfundene. "
        "Führe die Tests aus und berichte, welche neuen Tests fehlschlagen und warum. Solange der Fehler "
        "nicht behoben ist, ist das erwartet. Sollst du einen deiner Tests korrigieren, bearbeite deine Datei.",
    ),
    "developer": Role(
        ["read_file", "search_code", "edit_file", "write_file"], "production", "escalate",
        "Du bist der Entwickler im Team. Setze den Auftrag mit gezielten, minimalen Änderungen um. "
        "Erfülle die Anforderung vollständig, wie sie in Aufgabe, Docstrings und Tests beschrieben ist, "
        "nicht nur die Tests. Lies eine Datei, bevor du sie änderst, und nutze edit_file für bestehende Dateien. "
        "Testdateien sind für dich schreibgeschützt. Verlangt ein Test etwas, das weder in der Aufgabe noch in "
        "einem Docstring steht oder ihnen widerspricht, ändere den Code nicht dafür, sondern nenne den Test "
        "in deinem Bericht. Berichte zum Schluss, was du geändert hast.",
    ),
    "tester": Role(
        ["run_tests", "read_file"], "read_only", "fast",
        "Du bist der Tester im Team. Du änderst nichts. Führe immer alle Tests aus (run_tests ohne target), "
        "auch wenn der Auftrag einzelne Dateien nennt, und berichte, wie viele "
        "bestanden haben und wie viele fehlgeschlagen sind, und bei Fehlern die genaue Ursache laut Ausgabe.",
    ),
    "reviewer": Role(
        [*READ_TOOLS, "show_changes", "run_tests"], "read_only", "strong",
        "Du bist der Reviewer im Team. Du änderst nichts. Prüfe, ob die Änderungen (show_changes) die Aufgabe "
        "vollständig erfüllen. Gehe jede Anforderung aus der Aufgabe und aus den Docstrings der betroffenen "
        "Funktionen einzeln durch, auch beschriebene Fehlerfälle, und vergleiche sie mit dem Code. Prüfe auch "
        "die neu angelegten Testdateien: Jeder Test muss durch Aufgabe oder Docstring gedeckt sein. Ein Test oder "
        "eine Code-Regel, die mehr verlangt als beschrieben (erfundene Einschränkung), ist ebenfalls eine Lücke. "
        "Führe alle Tests aus (run_tests ohne target). Gib approved=true nur, wenn alles erfüllt ist, nichts "
        "erfunden wurde und alle Tests bestehen. Sonst nenne in issues jede Lücke konkret mit Datei und Funktion.",
    ),
}

SUPERVISOR_PROMPT = """Du bist der Supervisor eines Entwickler-Teams und steuerst die Arbeit an einer Aufgabe.

Dein Team:
- explorer: untersucht den Code, findet Fehlerursachen und nicht erfüllte Anforderungen. Ändert nichts.
- test_writer: schreibt neue Tests, die die Anforderungen vollständig abdecken. Ändert keinen Produktivcode.
- developer: ändert den Produktivcode. Darf keine Tests ändern.
- tester: führt die Tests aus und berichtet das Ergebnis. Ändert nichts.
- reviewer: prüft die Änderungen gegen die Anforderungen und gibt frei oder nennt Lücken. Ändert nichts.

Entscheide jeweils, wer als Nächstes arbeitet, und gib ihm einen klaren, konkreten Auftrag.
Die Fach-Agenten sehen nur die Aufgabe und deinen Auftrag, nicht die bisherigen Berichte.
Gib ihnen deshalb alle nötigen Informationen daraus mit (Dateien, Funktionen, Ursachen, Anforderungen).

Typischer Ablauf: explorer -> test_writer -> developer -> tester -> reviewer -> finish.
Schlagen Tests fehl oder findet der reviewer Lücken, geht es zurück zum developer.
Fehlen Tests, oder verlangt ein neuer Test mehr als Aufgabe und Docstrings (laut developer oder reviewer),
beauftrage den test_writer, ihn zu ergänzen bzw. zu korrigieren. Erfundene Anforderungen sind ein Fehler.
Abschließen (finish) kannst du erst, wenn die Tests bestehen und der reviewer freigegeben hat.
Fasse dann im Feld summary zusammen, was gemacht wurde.

Berichte von "mensch" sind Feedback des Nutzers zu deinem letzten Ergebnis.
Sie haben Vorrang: Setze das Feedback um und lass danach erneut testen und prüfen.
Berichte von "system" erklären, warum ein Abschluss abgelehnt wurde."""


class Decision(BaseModel):
    next: Literal["explorer", "test_writer", "developer", "tester", "reviewer", "finish"]
    instruction: str = Field(description="Konkreter Auftrag an den Fach-Agenten, leer bei finish")
    summary: str = Field(description="Abschlussbericht bei finish, sonst leer")


class ReviewVerdict(BaseModel):
    approved: bool = Field(description="True nur, wenn alle Anforderungen erfüllt sind und alle Tests bestehen")
    issues: list[str] = Field(description="Konkrete Lücken mit Datei und Funktion, leer bei Freigabe")
    summary: str = Field(description="Kurze Begründung")


class Report(TypedDict, total=False):
    agent: str
    model: str
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
    spec_approved: bool  # Freigabe durch den Reviewer, verfällt bei jeder Änderung
    review: Literal["approve", "reject", "feedback"]  # Entscheidung des Menschen


class ReviewAnswer(TypedDict, total=False):
    """Antwort des Menschen, mit der der Graph nach dem interrupt fortgesetzt wird."""
    action: Literal["approve", "reject", "feedback"]
    feedback: str


def format_reports(reports: list[Report]) -> str:
    if not reports:
        return "(noch keine)"
    return "\n\n".join(f"[{r['agent']}] Auftrag: {r['instruction']}\nBericht: {r['result']}" for r in reports)


def last_test_result(messages: list) -> bool | None:
    """Wertet die Werkzeugaufrufe aus: Haben die Tests zuletzt bestanden?

    Als bestanden zählt nur ein Lauf über alle Tests. Ein Teillauf (run_tests mit target)
    kann nur ein Fehlschlagen anzeigen. None, wenn nichts davon passiert ist.
    """
    targets = {call["id"]: call["args"].get("target") for m in messages if isinstance(m, AIMessage)
               for call in m.tool_calls}
    passed = None
    for message in messages:
        if isinstance(message, ToolMessage):
            if message.name == "run_tests":
                green = message.content.startswith("Exit-Code: 0")
                if not green or not targets.get(message.tool_call_id):
                    passed = green
            elif message.name in ("edit_file", "write_file"):
                passed = False
    return passed


def changed_files(messages: list) -> bool:
    return any(isinstance(m, ToolMessage) and m.name in ("edit_file", "write_file") and "Fehler" not in m.content
               for m in messages)


def pick_tier(role: ModelTier, name: str, reports: list[Report]) -> Literal["fast", "strong"]:
    """Bei escalate: günstig beim ersten Einsatz, stark sobald die Rolle nachbessern muss."""
    if role != "escalate":
        return role
    return "strong" if any(r["agent"] == name for r in reports) else "fast"


def verification_step(state: State) -> tuple[str, str] | None:
    """Was fehlt noch, bevor abgeschlossen werden darf? None, wenn die Lösung verifiziert ist."""
    if not state.get("tests_passed"):
        return "tester", "Führe alle Tests aus und berichte das Ergebnis."
    if not state.get("spec_approved"):
        return "reviewer", "Prüfe die Änderungen (show_changes) vollständig gegen die Aufgabe und die Docstrings."
    return None


def write_policies(repo: Path) -> dict[str, WritePolicy | None]:
    existing_tests = {p.relative_to(repo).as_posix() for p in iter_files(repo)
                      if is_test_file(p.relative_to(repo).as_posix())}

    def read_only(rel: str) -> str | None:
        return "Diese Rolle darf nichts ändern."

    def production(rel: str) -> str | None:
        return "Testdateien sind für den Entwickler schreibgeschützt." if is_test_file(rel) else None

    def new_tests(rel: str) -> str | None:
        if not is_test_file(rel):
            return "Der Test-Autor darf nur Testdateien schreiben (Name test_*.py)."
        if rel in existing_tests:
            return "Bestehende Testdateien sind schreibgeschützt. Lege eine neue Datei an, z. B. test_spec_<modul>.py."
        return None

    return {"read_only": read_only, "production": production, "new_tests": new_tests}


def build_team_graph(repo: Path, sandbox: bool = True, human_review: bool = True,
                     checkpointer: BaseCheckpointSaver | None = None):
    names = model_names()
    models = {tier: make_model(name) for tier, name in names.items()}
    toolsets = {name: {t.name: t for t in make_tools(repo, sandbox, policy)}
                for name, policy in write_policies(repo).items()}
    supervisor_llm = models["strong"].with_structured_output(Decision)

    def supervisor(state: State) -> State:
        rounds = state.get("rounds", 0)
        if rounds >= MAX_ROUNDS:
            return {"next": "finish", "summary": f"Abgebrochen: Rundenlimit ({MAX_ROUNDS}) erreicht."}
        decision = supervisor_llm.invoke([
            SystemMessage(SUPERVISOR_PROMPT),
            HumanMessage(f"Aufgabe: {state['task']}\n\nBisherige Berichte:\n{format_reports(state.get('reports', []))}"),
        ])
        update: State = {"next": decision.next, "instruction": decision.instruction,
                         "summary": decision.summary, "rounds": rounds + 1}
        # Guardrail im Code statt im Prompt: Ohne grüne Tests und Freigabe des Reviewers kein Abschluss.
        if decision.next == "finish" and (missing := verification_step(state)):
            update["next"], update["instruction"] = missing
            update["reports"] = [{"agent": "system", "instruction": "Abschluss geprüft",
                                  "result": f"Abschluss abgelehnt, noch nicht verifiziert. Weiter mit {missing[0]}."}]
        return update

    def make_worker(name: str, role: Role):
        tiers = ["fast", "strong"] if role.model == "escalate" else [role.model]
        agents = {tier: create_agent(
            models[tier],
            [toolsets[role.toolset][n] for n in role.tools],
            system_prompt=role.prompt + WORKER_RULES,
            middleware=[ModelCallLimitMiddleware(run_limit=WORKER_MODEL_CALLS)],
            response_format=ReviewVerdict if name == "reviewer" else None,
            name=name,
        ) for tier in tiers}

        def worker(state: State) -> State:
            tier = pick_tier(role.model, name, state.get("reports", []))
            result = agents[tier].invoke({"messages": [HumanMessage(
                f"Aufgabe des Teams: {state['task']}\n\nDein Auftrag: {state['instruction']}"
            )]})
            messages = result["messages"]
            text = messages[-1].text or "(kein Bericht)"
            update: State = {}
            if (verdict := result.get("structured_response")) is not None:
                update["spec_approved"] = verdict.approved
                text = f"Freigegeben: {'ja' if verdict.approved else 'nein'}. {verdict.summary}"
                text += "".join(f"\n- {issue}" for issue in verdict.issues)
            if changed_files(messages):
                update["spec_approved"] = False
            if (passed := last_test_result(messages)) is not None:
                update["tests_passed"] = passed
            update["reports"] = [{"agent": name, "model": names[tier], "instruction": state["instruction"],
                                  "result": text}]
            return update

        return worker

    def review(state: State) -> State:
        # Der Graph pausiert hier. Fortgesetzt wird mit Command(resume=ReviewAnswer).
        answer: ReviewAnswer = interrupt({"summary": state.get("summary", ""),
                                          "tests_passed": state.get("tests_passed")})
        if answer["action"] != "feedback":
            return {"review": answer["action"]}
        return {
            "review": "feedback",
            "rounds": 0,  # neues Rundenbudget für die Nacharbeit
            "spec_approved": False,
            "reports": [{"agent": "mensch", "instruction": "Prüfung des Ergebnisses", "result": answer["feedback"]}],
        }

    def route_after_supervisor(state: State) -> str:
        if state["next"] == "finish":
            return "review" if human_review else END
        return state["next"]

    def route_after_review(state: State) -> str:
        return "supervisor" if state["review"] == "feedback" else END

    graph = StateGraph(State)
    graph.add_node("supervisor", supervisor)
    for name, role in SPECIALISTS.items():
        graph.add_node(name, make_worker(name, role))
        graph.add_edge(name, "supervisor")
    graph.add_node("review", review)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_after_supervisor, [*SPECIALISTS, "review", END])
    graph.add_conditional_edges("review", route_after_review, ["supervisor", END])
    # Der Checkpointer speichert den Zustand nach jedem Schritt. Nur so kann der Graph
    # beim interrupt pausieren und später an derselben Stelle weiterlaufen.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
