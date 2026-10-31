from search import binary_search


def test_not_found_smaller_than_all():
    assert binary_search([5, 6, 7], 1) == -1


def test_not_found_between_values():
    assert binary_search([1, 3, 5, 7], 4) == -1


def test_large_list():
    items = list(range(0, 2000, 2))
    assert binary_search(items, 1998) == 999
    assert binary_search(items, 1999) == -1
