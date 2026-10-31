from shop.orders import invoice_line, order_total_cents


def test_total_cents():
    assert order_total_cents([19.99, 0.01]) == 2000


def test_invoice_line_with_cents():
    assert invoice_line([10.05]) == "Gesamt: 10,05 €"


def test_invoice_line_round_amount():
    assert invoice_line([5.0, 5.0]) == "Gesamt: 10,00 €"
