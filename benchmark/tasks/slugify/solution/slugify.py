"""URL-freundliche Bezeichner aus Texten."""
import re

UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def slugify(text: str) -> str:
    """Wandelt einen Text in einen Slug um, z. B. "Größe & Gewicht" -> "groesse-gewicht"."""
    text = text.lower()
    for umlaut, replacement in UMLAUTS.items():
        text = text.replace(umlaut, replacement)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")
