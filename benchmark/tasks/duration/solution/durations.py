"""Zeitangaben."""
import re


def parse_duration(text: str) -> int:
    """Wandelt eine Dauer wie "90s", "15m" oder "1h30m15s" in Sekunden um."""
    text = text.strip()
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    if not text or not match:
        raise ValueError(f"Ungültige Dauer: {text!r}")
    hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
    return hours * 3600 + minutes * 60 + seconds
