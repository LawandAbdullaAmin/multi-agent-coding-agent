from langchain_core.messages import AIMessage, ToolMessage

from coding_agent.team import changed_files, last_test_result, pick_tier, verification_step, write_policies


def test_developer_escalates_to_strong_model_on_second_attempt():
    assert pick_tier("escalate", "developer", []) == "fast"
    assert pick_tier("escalate", "developer", [{"agent": "explorer"}]) == "fast"
    assert pick_tier("escalate", "developer", [{"agent": "developer"}]) == "strong"
    assert pick_tier("strong", "reviewer", []) == "strong"
    assert pick_tier("fast", "tester", [{"agent": "tester"}]) == "fast"


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


def run_tests_call(call_id: str, target: str = "") -> AIMessage:
    return AIMessage("", tool_calls=[{"id": call_id, "name": "run_tests", "args": {"target": target} if target else {}}])


def test_only_full_test_run_counts_as_passed():
    partial = [run_tests_call("1", "test_a.py"), ToolMessage("Exit-Code: 0", name="run_tests", tool_call_id="1")]
    assert last_test_result(partial) is None
    partial_red = [run_tests_call("1", "test_a.py"), ToolMessage("Exit-Code: 1", name="run_tests", tool_call_id="1")]
    assert last_test_result(partial_red) is False
    full = [run_tests_call("2"), ToolMessage("Exit-Code: 0", name="run_tests", tool_call_id="2")]
    assert last_test_result(full) is True


def test_rejected_edits_are_not_changes():
    assert not changed_files([tool_result("edit_file", "Fehler: test_app.py darf nicht geändert werden.")])
    assert changed_files([tool_result("edit_file", "app.py geändert.")])


def test_finish_requires_green_tests_and_review():
    assert verification_step({})[0] == "tester"
    assert verification_step({"tests_passed": False, "spec_approved": True})[0] == "tester"
    assert verification_step({"tests_passed": True})[0] == "reviewer"
    assert verification_step({"tests_passed": True, "spec_approved": True}) is None


def test_write_policies(tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("", encoding="utf-8")
    policies = write_policies(tmp_path)

    assert policies["read_only"]("app.py")
    assert policies["production"]("app.py") is None
    assert policies["production"]("test_app.py")
    assert policies["production"]("tests/test_neu.py")
    assert policies["new_tests"]("test_spec_app.py") is None
    assert policies["new_tests"]("test_app.py")   # bestehender Test
    assert policies["new_tests"]("app.py")        # Produktivcode
