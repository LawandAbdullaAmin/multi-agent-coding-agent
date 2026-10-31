from pagination import page_count, paginate


def test_page_after_last_is_empty():
    assert paginate([1, 2, 3], 5, 2) == []


def test_single_item():
    assert page_count(1, 10) == 1
    assert paginate(["a"], 1, 10) == ["a"]


def test_second_page():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]
