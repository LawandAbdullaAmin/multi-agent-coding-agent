"""Übersetzt den Stream des Team-Graphen in verständliche Ereignisse für die Weboberfläche.

Die Oberfläche zeigt keinen Code und keine Rohausgaben, sondern Sätze wie
"Liest calculator.py" oder "4 von 6 Tests fehlgeschlagen".
"""

import re

from langchain_core.messages import AIMessage, ToolMessage

from coding_agent.team import SPECIALISTS


def describe_tool_call(name: str, args: dict) -> str:
    path = args.get("path", "")
    if name == "run_tests":
        return f"Führt die Tests in {args['target']} aus" if args.get("target") else "Führt alle Tests aus"
    return {
        "list_files": "Verschafft sich einen Überblick über das Projekt",
        "read_file": f"Liest {path}",
        "search_code": f"Sucht im Code nach „{args.get('pattern', '')}“",
        "write_file": f"Schreibt {path}",
        "edit_file": f"Ändert {path}",
        "show_changes": "Prüft alle Änderungen",
    }.get(name, name)


def summarize_tests(output: str) -> tuple[str, bool]:
    passed = int(match.group(1)) if (match := re.search(r"(\d+) passed", output)) else 0
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|errors?)\b", output))
    if output.startswith("Exit-Code: 0"):
        return f"{passed} Tests bestanden", True
    if passed + failed == 0:
        return "Tests konnten nicht ausgeführt werden", False
    return f"{failed} von {passed + failed} Tests fehlgeschlagen", False


def describe_tool_result(name: str, content: str) -> tuple[str, bool] | None:
    """Kurzfassung eines Werkzeugergebnisses, oder None, wenn es nicht erwähnenswert ist."""
    if content.startswith("Fehler"):
        if "darf nicht geändert werden" in content:
            return "Schreibschutz greift: Zugriff verweigert", False
        return content.splitlines()[0][:160], False
    if name == "run_tests":
        return summarize_tests(content)
    return None


class EventTranslator:
    """Merkt sich offene Werkzeugaufrufe, um Ergebnisse dem richtigen Aufruf zuzuordnen."""

    def __init__(self) -> None:
        self.pending: dict[str, str] = {}

    def translate(self, namespace: tuple, node: str, update: dict) -> list[dict]:
        if namespace:  # Schritt innerhalb eines Fach-Agenten, z. B. ("developer:<id>",)
            return self._agent_step(namespace[0].split(":")[0], update)

        events = []
        reports = update.get("reports") or []
        if node == "supervisor":
            for report in reports:  # Hinweis der Guardrail, falls ein Abschluss abgelehnt wurde
                events.append({"type": "guardrail", "text": report["result"]})
            target = update["next"]
            text = update.get("summary" if target == "finish" else "instruction", "")
            events.append({"type": "dispatch", "agent": target, "text": text})
        elif node in SPECIALISTS:
            for report in reports:
                event = {"type": "report", "agent": node, "model": report.get("model", ""), "text": report["result"]}
                if node == "reviewer":
                    event["approved"] = report["result"].startswith("Freigegeben: ja")
                events.append(event)
        else:
            for report in reports:  # Feedback des Menschen aus dem Knoten review
                events.append({"type": "feedback", "text": report["result"]})
        return events

    def _agent_step(self, agent: str, update: dict) -> list[dict]:
        events = []
        if agent not in SPECIALISTS:
            return events
        for message in update.get("messages") or []:
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    self.pending[call["id"]] = call["name"]
                    events.append({"type": "action", "agent": agent, "tool": call["name"],
                                   "text": describe_tool_call(call["name"], call["args"])})
            elif isinstance(message, ToolMessage):
                name = self.pending.pop(message.tool_call_id, message.name or "")
                if summary := describe_tool_result(name, message.content):
                    events.append({"type": "observation", "agent": agent, "text": summary[0], "ok": summary[1]})
        return events
