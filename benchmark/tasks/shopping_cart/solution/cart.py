"""Warenkorb."""


class Cart:
    def __init__(self, items: list[tuple[str, float]] | None = None):
        """Erstellt einen Warenkorb. Eine übergebene Liste wird kopiert, nicht verändert."""
        self.items = list(items or [])

    def add(self, name: str, price: float) -> None:
        if price < 0:
            raise ValueError("Preis darf nicht negativ sein")
        self.items.append((name, price))

    def total(self) -> float:
        return round(sum(price for _, price in self.items), 2)

    def total_with_discount(self, percent: float) -> float:
        """Gesamtpreis abzüglich `percent` Prozent Rabatt."""
        return round(self.total() * (1 - percent / 100), 2)
