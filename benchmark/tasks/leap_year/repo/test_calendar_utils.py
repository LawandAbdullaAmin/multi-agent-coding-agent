from calendar_utils import days_in_month, is_leap_year


def test_regular_leap_years():
    assert is_leap_year(2024)
    assert not is_leap_year(2023)


def test_century_rule():
    assert not is_leap_year(1900)
    assert is_leap_year(2000)


def test_february():
    assert days_in_month(2024, 2) == 29
    assert days_in_month(1900, 2) == 28


def test_short_month():
    assert days_in_month(2024, 4) == 30
