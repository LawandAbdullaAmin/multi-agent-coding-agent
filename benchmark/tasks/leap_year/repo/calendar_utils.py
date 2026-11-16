"""Calendar functions."""


def is_leap_year(year: int) -> bool:
    """Leap year according to the Gregorian calendar."""
    return year % 4 == 0


def days_in_month(year: int, month: int) -> int:
    """Number of days in the month (1 to 12). Raises ValueError for an invalid month."""
    if month == 2:
        return 29 if is_leap_year(year) else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31
