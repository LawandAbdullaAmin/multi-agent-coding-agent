"""Durations."""
import re


def parse_duration(text: str) -> int:
    """Converts a duration such as "90s", "15m" or "1h30m15s" into seconds."""
    text = text.strip()
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    if not text or not match:
        raise ValueError(f"Invalid duration: {text!r}")
    hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
    return hours * 3600 + minutes * 60 + seconds
