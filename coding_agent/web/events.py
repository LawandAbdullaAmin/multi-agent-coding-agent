"""Translates the team graph's stream into readable events for the web interface.

The interface shows no code and no raw output, but sentences such as
"Reads calculator.py" or "4 of 6 tests failed".
"""

import re

from langchain_core.messages import AIMessage, ToolMessage

from coding_agent.team import SPECIALISTS
from coding_agent.tools import tests_green


def describe_tool_call(name: str, args: dict) -> str:
    path = args.get("path", "")
    if name == "run_tests":
        return f"Runs the tests in {args['target']}" if args.get("target") else "Runs all tests"
    return {
        "list_files": "Gets an overview of the project",
        "read_file": f"Reads {path}",
        "search_code": f"Searches the code for “{args.get('pattern', '')}”",
        "write_file": f"Writes {path}",
        "edit_file": f"Edits {path}",
        "show_changes": "Reviews all changes",
    }.get(name, name)


def summarize_tests(output: str) -> tuple[str, bool]:
    passed = int(match.group(1)) if (match := re.search(r"(\d+) passed", output)) else 0
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|errors?)\b", output))
    if tests_green(output):
        return f"{passed} tests passed", True
    if passed + failed == 0:
        return "Tests could not be run", False
    return f"{failed} of {passed + failed} tests failed", False


def describe_tool_result(name: str, content: str, error: bool) -> tuple[str, bool] | None:
    """Short summary of a tool result, or None if it is not worth mentioning."""
    if error:
        if "must not be changed" in content:
            return "Write protection kicked in: access denied", False
        return content.splitlines()[0][:160], False
    if name == "run_tests":
        return summarize_tests(content)
    return None


class EventTranslator:
    """Keeps track of open tool calls to match results to the right call."""

    def __init__(self) -> None:
        self.pending: dict[str, str] = {}

    def translate(self, namespace: tuple, node: str, update: dict) -> list[dict]:
        if namespace:  # step inside a specialist agent, e.g. ("developer:<id>",)
            return self._agent_step(namespace[0].split(":")[0], update)

        events = []
        reports = update.get("reports") or []
        if node == "supervisor":
            for report in reports:  # guardrail notice if finishing was rejected
                events.append({"type": "guardrail", "text": report["result"]})
            target = update["next"]
            text = update.get("summary" if target == "finish" else "instruction", "")
            events.append({"type": "dispatch", "agent": target, "text": text})
        elif node in SPECIALISTS:
            for report in reports:
                event = {"type": "report", "agent": node, "model": report.get("model", ""), "text": report["result"]}
                if node == "reviewer":
                    event["approved"] = report["result"].startswith("Approved: yes")
                events.append(event)
        else:
            for report in reports:  # human feedback from the review node
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
                if summary := describe_tool_result(name, message.content, message.status == "error"):
                    events.append({"type": "observation", "agent": agent, "text": summary[0], "ok": summary[1]})
        return events
