"""Einfache Rechenfunktionen."""


def add(a: float, b: float) -> float:
    return a + b


def divide(a: float, b: float) -> float:
    """Teilt a durch b. Wirft ValueError, wenn b gleich 0 ist."""
    return a / b


def average(numbers: list[float]) -> float:
    """Durchschnitt der Zahlen. Bei einer leeren Liste 0.0."""
    return sum(numbers) / len(numbers)


def percent_change(old: float, new: float) -> float:
    """Prozentuale Veränderung von old zu new, z. B. 50 -> 75 ergibt 50.0."""
    return (new - old) / new * 100
