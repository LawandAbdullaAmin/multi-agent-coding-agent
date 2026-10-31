import pytest

from calendar_utils import days_in_month, is_leap_year


def test_more_centuries():
    assert not is_leap_year(2100)
    assert is_leap_year(2400)


@pytest.mark.parametrize("month", [0, 13, -1])
def test_invalid_month_raises(month):
    with pytest.raises(ValueError):
        days_in_month(2024, month)


def test_december():
    assert days_in_month(2023, 12) == 31
