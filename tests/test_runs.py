from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from coding_agent import runs
from coding_agent.runs import Run, load_run, open_checkpointer, save_run


@pytest.fixture(autouse=True)
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)


def test_save_and_load_run():
    run = Run(id="demo-1", task="Fix", repo="C:/repo", workspace="C:/ws", mode="team",
              sandbox=True, human_review=True, in_place=False)
    save_run(run)
    assert load_run("demo-1") == run


def test_load_unknown_run_fails():
    with pytest.raises(FileNotFoundError):
        load_run("gibt-es-nicht")


class State(TypedDict, total=False):
    answer: str


def build_graph(checkpointer):
    graph = StateGraph(State)
    graph.add_node("ask", lambda state: {"answer": interrupt("Frage")})
    graph.add_edge(START, "ask")
    graph.add_edge("ask", END)
    return graph.compile(checkpointer=checkpointer)


def test_interrupted_run_can_be_resumed_after_restart():
    config = {"configurable": {"thread_id": "demo-1"}}

    first = open_checkpointer()
    build_graph(first).invoke({}, config)
    first.conn.close()  # simuliert: Programm beendet

    second = open_checkpointer()
    app = build_graph(second)
    assert app.get_state(config).interrupts
    assert app.invoke(Command(resume="42"), config) == {"answer": "42"}
    second.conn.close()
