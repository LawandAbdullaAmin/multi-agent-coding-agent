from coding_agent.__main__ import apply_changes, changed_files, parse_review_answer


def test_parse_review_answer():
    assert parse_review_answer("") == {"action": "approve"}
    assert parse_review_answer(" Ja ") == {"action": "approve"}
    assert parse_review_answer("n") == {"action": "reject"}
    assert parse_review_answer("Bitte auf Englisch") == {"action": "feedback", "feedback": "Bitte auf Englisch"}


def test_apply_changes_copies_only_changed_and_new_files(tmp_path):
    original, workspace = tmp_path / "repo", tmp_path / "ws"
    for folder in (original, workspace):
        folder.mkdir()
        (folder / "same.py").write_text("a = 1\n", encoding="utf-8")
    (original / "app.py").write_text("x = 1\n", encoding="utf-8")
    (workspace / "app.py").write_text("x = 2\n", encoding="utf-8")
    (workspace / "new.py").write_text("y = 1\n", encoding="utf-8")

    assert sorted(p.as_posix() for p in changed_files(original, workspace)) == ["app.py", "new.py"]
    apply_changes(original, workspace)
    assert (original / "app.py").read_text(encoding="utf-8") == "x = 2\n"
    assert (original / "new.py").read_text(encoding="utf-8") == "y = 1\n"
    assert changed_files(original, workspace) == []
