import pytest

from roman import roman_to_int


@pytest.mark.parametrize("text, expected", [("XL", 40), ("CD", 400), ("MMXXVI", 2026), ("III", 3), ("XC", 90)])
def test_more_conversions(text, expected):
    assert roman_to_int(text) == expected


@pytest.mark.parametrize("text", ["", "Z", "X1"])
def test_invalid_input(text):
    with pytest.raises(ValueError):
        roman_to_int(text)
