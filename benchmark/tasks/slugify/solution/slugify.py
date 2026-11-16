"""URL-friendly identifiers from texts."""
import re

UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def slugify(text: str) -> str:
    """Converts a text into a slug, e.g. "Größe & Gewicht" -> "groesse-gewicht"."""
    text = text.lower()
    for umlaut, replacement in UMLAUTS.items():
        text = text.replace(umlaut, replacement)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")
