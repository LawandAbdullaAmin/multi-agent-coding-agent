"""Kalenderfunktionen."""


def is_leap_year(year: int) -> bool:
    """Schaltjahr nach dem gregorianischen Kalender."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    """Anzahl der Tage im Monat (1 bis 12). Wirft ValueError bei einem ungültigen Monat."""
    if not 1 <= month <= 12:
        raise ValueError(f"Ungültiger Monat: {month}")
    if month == 2:
        return 29 if is_leap_year(year) else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31
