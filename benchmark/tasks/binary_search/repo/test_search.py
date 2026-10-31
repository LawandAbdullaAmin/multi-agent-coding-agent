from search import binary_search


def test_found():
    assert binary_search([1, 3, 5, 7, 9], 7) == 3


def test_first_and_last():
    assert binary_search([1, 3, 5], 1) == 0
    assert binary_search([1, 3, 5], 5) == 2


def test_not_found_larger_than_all():
    assert binary_search([1, 2, 3], 4) == -1


def test_empty_list():
    assert binary_search([], 1) == -1
