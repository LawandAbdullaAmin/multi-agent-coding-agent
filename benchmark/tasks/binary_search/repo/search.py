"""Searching in sorted lists."""


def binary_search(items: list[int], target: int) -> int:
    """Index of target in the ascending sorted list items, -1 if not contained."""
    lo, hi = 0, len(items)
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
