"""Orders."""
from shop.money import format_euros, to_cents


def order_total_cents(prices: list[float]) -> int:
    """Sum of the prices in cents."""
    return sum(to_cents(price) for price in prices)


def invoice_line(prices: list[float]) -> str:
    return f"Total: {format_euros(order_total_cents(prices))}"
