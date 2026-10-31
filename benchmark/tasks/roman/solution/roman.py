"""Römische Zahlen."""

VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(text: str) -> int:
    """Wandelt eine römische Zahl in eine ganze Zahl um, z. B. "XIV" -> 14.

    Erlaubt sind die Zeichen I, V, X, L, C, D und M. Bei anderen Zeichen
    oder einem leeren Text wird ein ValueError geworfen.
    """
    if not text or any(char not in VALUES for char in text):
        raise ValueError(f"Ungültige römische Zahl: {text!r}")
    total = 0
    for i, char in enumerate(text):
        value = VALUES[char]
        if i + 1 < len(text) and VALUES[text[i + 1]] > value:
            total -= value
        else:
            total += value
    return total
