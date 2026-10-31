"""Bestellungen."""
from shop.money import format_euros, to_cents


def order_total_cents(prices: list[float]) -> int:
    """Summe der Preise in Cent."""
    return sum(to_cents(price) for price in prices)


def invoice_line(prices: list[float]) -> str:
    return f"Gesamt: {format_euros(order_total_cents(prices))}"
