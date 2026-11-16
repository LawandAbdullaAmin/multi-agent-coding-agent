"""Roman numerals."""

VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(text: str) -> int:
    """Converts a Roman numeral into an integer, e.g. "XIV" -> 14.

    The allowed characters are I, V, X, L, C, D and M. For other characters
    or an empty text, a ValueError is raised.
    """
    if not text or any(char not in VALUES for char in text):
        raise ValueError(f"Invalid Roman numeral: {text!r}")
    total = 0
    for i, char in enumerate(text):
        value = VALUES[char]
        if i + 1 < len(text) and VALUES[text[i + 1]] > value:
            total -= value
        else:
            total += value
    return total
