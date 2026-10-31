from pagination import page_count, paginate


def test_page_count_exact():
    assert page_count(20, 10) == 2


def test_page_count_with_rest():
    assert page_count(21, 10) == 3


def test_page_count_empty():
    assert page_count(0, 10) == 0


def test_first_page():
    assert paginate(list(range(25)), 1, 10) == list(range(10))


def test_last_page():
    assert paginate(list(range(25)), 3, 10) == [20, 21, 22, 23, 24]
