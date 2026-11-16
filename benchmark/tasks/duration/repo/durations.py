"""Durations."""
import re


def parse_duration(text: str) -> int:
    """Converts a duration such as "90s" or "15m" into seconds."""
    match = re.fullmatch(r"(\d+)([sm])", text.strip())
    if not match:
        raise ValueError(f"Invalid duration: {text!r}")
    value, unit = int(match.group(1)), match.group(2)
    return value * 60 if unit == "m" else value
