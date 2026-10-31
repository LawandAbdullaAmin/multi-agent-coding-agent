import pytest

from roman import roman_to_int


@pytest.mark.parametrize("text, expected", [("I", 1), ("IV", 4), ("IX", 9), ("XIV", 14), ("MCMXCIV", 1994)])
def test_conversion(text, expected):
    assert roman_to_int(text) == expected


def test_invalid_characters():
    with pytest.raises(ValueError):
        roman_to_int("ABC")
