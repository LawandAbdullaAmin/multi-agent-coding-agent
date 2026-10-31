from shop.money import format_euros, to_cents
from shop.orders import order_total_cents


def test_small_amount():
    assert format_euros(5) == "0,05 €"


def test_tricky_floats():
    assert to_cents(0.29) == 29
    assert to_cents(1.15) == 115


def test_empty_order():
    assert order_total_cents([]) == 0
