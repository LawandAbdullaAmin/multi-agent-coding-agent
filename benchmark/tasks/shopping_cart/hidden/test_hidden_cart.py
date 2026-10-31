from cart import Cart


def test_given_list_is_not_modified():
    items = [("A", 1.0)]
    cart = Cart(items)
    cart.add("B", 2.0)
    assert items == [("A", 1.0)]
    assert cart.total() == 3.0


def test_zero_discount():
    cart = Cart()
    cart.add("Buch", 12.5)
    assert cart.total_with_discount(0) == 12.5


def test_new_cart_is_empty():
    Cart().add("Apfel", 1.0)
    assert Cart().total() == 0
