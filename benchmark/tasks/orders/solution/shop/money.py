"""Hilfsfunktionen für Geldbeträge. Intern wird in Cent gerechnet, um Rundungsfehler zu vermeiden."""


def to_cents(euros: float) -> int:
    return round(euros * 100)


def format_euros(cents: int) -> str:
    """Formatiert Cent als Euro-Betrag, z. B. 1999 -> '19,99 €'."""
    return f"{cents // 100},{cents % 100:02d} €"
