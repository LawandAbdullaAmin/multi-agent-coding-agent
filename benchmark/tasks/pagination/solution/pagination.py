"""Seitenweise Ausgabe von Listen."""
import math


def page_count(total_items: int, per_page: int) -> int:
    """Anzahl der Seiten. 0 Einträge ergeben 0 Seiten."""
    return math.ceil(total_items / per_page)


def paginate(items: list, page: int, per_page: int) -> list:
    """Gibt die Einträge der Seite `page` zurück. Die erste Seite ist Seite 1."""
    start = (page - 1) * per_page
    return items[start:start + per_page]
