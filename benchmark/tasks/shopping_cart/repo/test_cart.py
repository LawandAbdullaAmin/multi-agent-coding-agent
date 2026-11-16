import pytest

from cart import Cart


def test_total():
    cart = Cart()
    cart.add("Apple", 0.5)
    cart.add("Bread", 2.25)
    assert cart.total() == 2.75


def test_carts_are_independent():
    first, second = Cart(), Cart()
    first.add("Apple", 1.0)
    assert second.items == []


def test_discount():
    cart = Cart()
    cart.add("Book", 20.0)
    assert cart.total_with_discount(25) == 15.0


def test_negative_price():
    with pytest.raises(ValueError):
        Cart().add("X", -1)
