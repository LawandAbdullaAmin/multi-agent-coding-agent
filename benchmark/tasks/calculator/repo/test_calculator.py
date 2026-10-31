import pytest

from calculator import add, average, divide, percent_change


def test_add():
    assert add(2, 3) == 5


def test_divide():
    assert divide(10, 4) == 2.5


def test_divide_by_zero_raises_value_error():
    with pytest.raises(ValueError):
        divide(1, 0)


def test_average():
    assert average([1, 2, 3, 4]) == 2.5


def test_average_of_empty_list_is_zero():
    assert average([]) == 0.0


def test_percent_change():
    assert percent_change(50, 75) == 50.0
    assert percent_change(200, 150) == -25.0
