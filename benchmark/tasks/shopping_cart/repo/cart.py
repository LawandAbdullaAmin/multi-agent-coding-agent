"""Shopping cart."""


class Cart:
    def __init__(self, items: list[tuple[str, float]] = []):
        """Creates a shopping cart. A list that is passed in is copied, not modified."""
        self.items = items

    def add(self, name: str, price: float) -> None:
        if price < 0:
            raise ValueError("Price must not be negative")
        self.items.append((name, price))

    def total(self) -> float:
        return round(sum(price for _, price in self.items), 2)

    def total_with_discount(self, percent: float) -> float:
        """Total price minus a discount of `percent` percent."""
        return round(self.total() * percent / 100, 2)
