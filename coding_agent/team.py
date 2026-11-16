"""Coding agent: a supervisor with specialist agents and human approval.

Flow:
    supervisor -> explorer | test_writer | developer | tester | reviewer -> supervisor -> ... -> review -> END
                                                                                                 |
                                                                  human feedback -> supervisor <+

The supervisor is its own LangGraph node. It uses structured output to decide
which specialist works next and with which instruction.
The specialists are built with create_agent. Their permissions are enforced in code:
only the developer changes production code, only the test writer creates new tests,
and existing tests are read-only for everyone.
The supervisor can only finish once the tests pass and the reviewer has approved
the solution against the requirements (verified).
Roles that have to make judgments use a strong model, routine roles a cheap one.
The developer starts on the cheap model and switches to the strong one as soon as it has to rework something.
In the review node the graph pauses (interrupt) until a human approves,
rejects or gives feedback on the result.
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

from coding_agent.tools import WritePolicy, is_test_file, iter_files, make_tools, tests_green

MAX_ROUNDS = 15
WORKER_MODEL_CALLS = 15

WORKER_RULES = ("\n\nYou work autonomously in an automated pipeline. Nobody answers questions: "
                "do not ask any, complete your instruction fully and then report.")

READ_TOOLS = ["list_files", "read_file", "search_code"]

ModelTier = Literal["fast", "strong", "escalate"]


class Role(NamedTuple):
    tools: list[str]
    toolset: str      # toolset with the role's write permissions, see write_policies
    model: ModelTier  # escalate: cheap on the first run, strong on every later one
    prompt: str


def model_names() -> dict[str, str]:
    return {"fast": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "strong": os.getenv("OPENAI_STRONG_MODEL", "gpt-4.1")}


def make_model(name: str) -> ChatOpenAI:
    # Reasoning models (gpt-5, o3, ...) do not support temperature.
    return ChatOpenAI(model=name, temperature=0) if name.startswith("gpt-4") else ChatOpenAI(model=name)


SPECIALISTS = {
    "explorer": Role(
        READ_TOOLS, "read_only", "fast",
        "You are the code explorer on the team. You change nothing. Investigate the repository and report briefly: "
        "relevant files, the cause of every bug with line numbers, and exactly what has to change. "
        "Also check whether the code does everything that docstrings and comments promise, "
        "even if no test checks it (e.g. documented error cases).",
    ),
    "test_writer": Role(
        [*READ_TOOLS, "write_file", "edit_file", "run_tests"], "new_tests", "strong",
        "You are the test writer on the team. Before the code is changed, you write tests that fully describe the "
        "desired behavior: from the task, from docstrings and comments, and from your instruction. "
        "Pay special attention to edge and error cases that are documented but not yet tested. "
        "Put the tests in a new file, e.g. test_spec_<module>.py. You must not change existing test files or "
        "production code. Only test what is explicitly required or documented: "
        "above every test, write a comment with the verbatim quote from the task or docstring that justifies it. "
        "Without such a quote, do not write the test. Make no assumptions of your own about formats, "
        "limits, value ranges or additional error cases. A few correct tests are better than many invented ones. "
        "Run the tests and report which new tests fail and why. As long as the bug "
        "is not fixed, that is expected. If you are asked to fix one of your tests, edit your file.",
    ),
    "developer": Role(
        ["read_file", "search_code", "edit_file", "write_file"], "production", "escalate",
        "You are the developer on the team. Carry out the instruction with targeted, minimal changes. "
        "Fulfill the requirement completely as described in the task, docstrings and tests, "
        "not just the tests. Read a file before you change it, and use edit_file for existing files. "
        "Test files are read-only for you. If a test requires something that is neither in the task nor in "
        "a docstring, or contradicts them, do not change the code for it; name the test "
        "in your report instead. Finally, report what you changed.",
    ),
    "tester": Role(
        ["run_tests", "read_file"], "read_only", "fast",
        "You are the tester on the team. You change nothing. Always run all tests (run_tests without target), "
        "even if the instruction names individual files, and report how many "
        "passed and how many failed, and for failures the exact cause according to the output.",
    ),
    "reviewer": Role(
        [*READ_TOOLS, "show_changes", "run_tests"], "read_only", "strong",
        "You are the reviewer on the team. You change nothing. Check whether the changes (show_changes) fully "
        "fulfill the task. Go through every requirement from the task and from the docstrings of the affected "
        "functions one by one, including documented error cases, and compare them with the code. Also check "
        "the newly created test files: every test must be covered by the task or a docstring. A test or "
        "a code rule that requires more than described (an invented restriction) is also a gap. "
        "Run all tests (run_tests without target). Set approved=true only if everything is fulfilled, nothing "
        "was invented and all tests pass. Otherwise list every gap in issues, concretely with file and function.",
    ),
}

SUPERVISOR_PROMPT = """You are the supervisor of a developer team and steer the work on a task.

Your team:
- explorer: investigates the code, finds bug causes and unmet requirements. Changes nothing.
- test_writer: writes new tests that fully cover the requirements. Does not change production code.
- developer: changes the production code. Must not change tests.
- tester: runs the tests and reports the result. Changes nothing.
- reviewer: checks the changes against the requirements and approves or names gaps. Changes nothing.

Each time, decide who works next and give them a clear, concrete instruction.
The specialists only see the task and your instruction, not the previous reports.
So pass on all the information they need from those reports (files, functions, causes, requirements).

Typical flow: explorer -> test_writer -> developer -> tester -> reviewer -> finish.
If tests fail or the reviewer finds gaps, go back to the developer.
If tests are missing, or a new test requires more than the task and docstrings (according to developer or reviewer),
instruct the test_writer to add or correct it. Invented requirements are a mistake.
You can only finish once the tests pass and the reviewer has approved.
Then summarize what was done in the summary field.

Reports from "human" are the user's feedback on your last result.
They take priority: implement the feedback and then have it tested and reviewed again.
Reports from "system" explain why finishing was rejected."""


class Decision(BaseModel):
    next: Literal["explorer", "test_writer", "developer", "tester", "reviewer", "finish"]
    instruction: str = Field(description="Concrete instruction for the specialist, empty on finish")
    summary: str = Field(description="Final report on finish, otherwise empty")


class ReviewVerdict(BaseModel):
    approved: bool = Field(description="True only if all requirements are met and all tests pass")
    issues: list[str] = Field(description="Concrete gaps with file and function, empty on approval")
    summary: str = Field(description="Short justification")


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
    spec_approved: bool  # reviewer approval, reset by every change
    review: Literal["approve", "reject", "feedback"]  # the human's decision


class ReviewAnswer(TypedDict, total=False):
    """The human's answer that resumes the graph after the interrupt."""
    action: Literal["approve", "reject", "feedback"]
    feedback: str


def format_reports(reports: list[Report]) -> str:
    if not reports:
        return "(none yet)"
    return "\n\n".join(f"[{r['agent']}] Instruction: {r['instruction']}\nReport: {r['result']}" for r in reports)


def is_write(message) -> bool:
    """Did this tool call actually change a file? Rejected attempts do not count."""
    return (isinstance(message, ToolMessage) and message.name in ("edit_file", "write_file")
            and message.status != "error")


def last_test_result(messages: list) -> bool | None:
    """Evaluates the tool calls: did the tests pass most recently?

    Only a run over all tests counts as passed. A partial run (run_tests with target)
    can only signal a failure. Any change afterwards invalidates the result.
    None if none of this happened.
    """
    targets = {call["id"]: call["args"].get("target") for m in messages if isinstance(m, AIMessage)
               for call in m.tool_calls}
    passed = None
    for message in messages:
        if isinstance(message, ToolMessage) and message.name == "run_tests":
            green = tests_green(message.content)
            if not green or not targets.get(message.tool_call_id):
                passed = green
        elif is_write(message):
            passed = False
    return passed


def wrote_files(messages: list) -> bool:
    return any(is_write(m) for m in messages)


def pick_tier(role: ModelTier, name: str, reports: list[Report]) -> Literal["fast", "strong"]:
    """For escalate: cheap on the first run, strong as soon as the role has to rework something."""
    if role != "escalate":
        return role
    return "strong" if any(r["agent"] == name for r in reports) else "fast"


def verification_step(state: State) -> tuple[str, str] | None:
    """What is still missing before finishing is allowed? None if the solution is verified."""
    if not state.get("tests_passed"):
        return "tester", "Run all tests and report the result."
    if not state.get("spec_approved"):
        return "reviewer", "Check the changes (show_changes) completely against the task and the docstrings."
    return None


def write_policies(repo: Path) -> dict[str, WritePolicy | None]:
    existing_tests = {p.relative_to(repo).as_posix() for p in iter_files(repo)
                      if is_test_file(p.relative_to(repo).as_posix())}

    def read_only(rel: str) -> str | None:
        return "This role must not change anything."

    def production(rel: str) -> str | None:
        return "Test files are read-only for the developer." if is_test_file(rel) else None

    def new_tests(rel: str) -> str | None:
        if not is_test_file(rel):
            return "The test writer may only write test files (named test_*.py)."
        if rel in existing_tests:
            return "Existing test files are read-only. Create a new file, e.g. test_spec_<module>.py."
        return None

    return {"read_only": read_only, "production": production, "new_tests": new_tests}


def build_team_graph(repo: Path, sandbox: bool = True, human_review: bool = True,
                     checkpointer: BaseCheckpointSaver | None = None, models: dict[str, str] | None = None):
    names = models or model_names()
    llms = {tier: make_model(name) for tier, name in names.items()}
    toolsets = {name: {t.name: t for t in make_tools(repo, sandbox, policy)}
                for name, policy in write_policies(repo).items()}
    supervisor_llm = llms["strong"].with_structured_output(Decision)

    def supervisor(state: State) -> State:
        rounds = state.get("rounds", 0)
        if rounds >= MAX_ROUNDS:
            return {"next": "finish", "summary": f"Aborted: round limit ({MAX_ROUNDS}) reached."}
        decision = supervisor_llm.invoke([
            SystemMessage(SUPERVISOR_PROMPT),
            HumanMessage(f"Task: {state['task']}\n\nReports so far:\n{format_reports(state.get('reports', []))}"),
        ])
        update: State = {"next": decision.next, "instruction": decision.instruction,
                         "summary": decision.summary, "rounds": rounds + 1}
        # Guardrail in code instead of the prompt: no finish without green tests and reviewer approval.
        if decision.next == "finish" and (missing := verification_step(state)):
            update["next"], update["instruction"] = missing
            update["reports"] = [{"agent": "system", "instruction": "Finish checked",
                                  "result": f"Finish rejected, not verified yet. Continuing with {missing[0]}."}]
        return update

    def make_worker(name: str, role: Role):
        tiers = ["fast", "strong"] if role.model == "escalate" else [role.model]
        agents = {tier: create_agent(
            llms[tier],
            [toolsets[role.toolset][n] for n in role.tools],
            system_prompt=role.prompt + WORKER_RULES,
            middleware=[ModelCallLimitMiddleware(run_limit=WORKER_MODEL_CALLS)],
            response_format=ReviewVerdict if name == "reviewer" else None,
            name=name,
        ) for tier in tiers}

        def worker(state: State) -> State:
            tier = pick_tier(role.model, name, state.get("reports", []))
            result = agents[tier].invoke({"messages": [HumanMessage(
                f"Team task: {state['task']}\n\nYour instruction: {state['instruction']}"
            )]})
            messages = result["messages"]
            text = messages[-1].text or "(no report)"
            update: State = {}
            if (verdict := result.get("structured_response")) is not None:
                update["spec_approved"] = verdict.approved
                text = f"Approved: {'yes' if verdict.approved else 'no'}. {verdict.summary}"
                text += "".join(f"\n- {issue}" for issue in verdict.issues)
            if wrote_files(messages):
                update["spec_approved"] = False
            if (passed := last_test_result(messages)) is not None:
                update["tests_passed"] = passed
            update["reports"] = [{"agent": name, "model": names[tier], "instruction": state["instruction"],
                                  "result": text}]
            return update

        return worker

    def review(state: State) -> State:
        # The graph pauses here. It is resumed with Command(resume=ReviewAnswer).
        answer: ReviewAnswer = interrupt({"summary": state.get("summary", ""),
                                          "tests_passed": state.get("tests_passed")})
        if answer["action"] != "feedback":
            return {"review": answer["action"]}
        return {
            "review": "feedback",
            "rounds": 0,  # fresh round budget for the rework
            "spec_approved": False,
            "reports": [{"agent": "human", "instruction": "Review of the result", "result": answer["feedback"]}],
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
    # The checkpointer saves the state after every step. This is what lets the graph
    # pause at the interrupt and later continue from the same point.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
