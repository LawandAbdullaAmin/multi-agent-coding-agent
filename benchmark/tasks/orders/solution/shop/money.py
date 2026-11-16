"""Helper functions for money amounts. Internally everything is calculated in cents to avoid rounding errors."""


def to_cents(euros: float) -> int:
    return round(euros * 100)


def format_euros(cents: int) -> str:
    """Formats cents as a euro amount, e.g. 1999 -> '19,99 €'."""
    return f"{cents // 100},{cents % 100:02d} €"
