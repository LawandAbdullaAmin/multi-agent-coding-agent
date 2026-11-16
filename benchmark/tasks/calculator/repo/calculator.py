"""Simple arithmetic functions."""


def add(a: float, b: float) -> float:
    return a + b


def divide(a: float, b: float) -> float:
    """Divides a by b. Raises ValueError if b is 0."""
    return a / b


def average(numbers: list[float]) -> float:
    """Average of the numbers. 0.0 for an empty list."""
    return sum(numbers) / len(numbers)


def percent_change(old: float, new: float) -> float:
    """Percentage change from old to new, e.g. 50 -> 75 gives 50.0."""
    return (new - old) / new * 100
