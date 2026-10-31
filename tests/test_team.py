from langchain_core.messages import AIMessage, ToolMessage

from coding_agent.team import last_test_result


def tool_result(name: str, content: str) -> ToolMessage:
    return ToolMessage(content, name=name, tool_call_id="1")


def test_no_tests_and_no_edits_is_unknown():
    assert last_test_result([AIMessage("fertig"), tool_result("read_file", "x = 1")]) is None


def test_last_test_run_counts():
    messages = [tool_result("run_tests", "Exit-Code: 1\n..F"), tool_result("run_tests", "Exit-Code: 0\n...")]
    assert last_test_result(messages) is True


def test_edit_after_green_tests_invalidates_result():
    messages = [tool_result("run_tests", "Exit-Code: 0\n..."), tool_result("edit_file", "app.py geändert.")]
    assert last_test_result(messages) is False
