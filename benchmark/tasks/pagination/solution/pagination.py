"""Splitting lists into pages."""
import math


def page_count(total_items: int, per_page: int) -> int:
    """Number of pages. 0 items give 0 pages."""
    return math.ceil(total_items / per_page)


def paginate(items: list, page: int, per_page: int) -> list:
    """Returns the items of page `page`. The first page is page 1."""
    start = (page - 1) * per_page
    return items[start:start + per_page]
