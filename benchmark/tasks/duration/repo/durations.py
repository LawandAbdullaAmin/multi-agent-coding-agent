"""Zeitangaben."""
import re


def parse_duration(text: str) -> int:
    """Wandelt eine Dauer wie "90s" oder "15m" in Sekunden um."""
    match = re.fullmatch(r"(\d+)([sm])", text.strip())
    if not match:
        raise ValueError(f"Ungültige Dauer: {text!r}")
    value, unit = int(match.group(1)), match.group(2)
    return value * 60 if unit == "m" else value
