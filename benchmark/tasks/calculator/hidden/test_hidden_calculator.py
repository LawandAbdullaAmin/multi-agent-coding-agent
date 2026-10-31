from calculator import average, divide, percent_change


def test_divide_negative():
    assert divide(-9, 3) == -3


def test_average_single_value():
    assert average([7]) == 7


def test_percent_change_no_change():
    assert percent_change(80, 80) == 0.0


def test_divide_zero_numerator_is_fine():
    assert divide(0, 5) == 0
