"""Suchen in sortierten Listen."""


def binary_search(items: list[int], target: int) -> int:
    """Index von target in der aufsteigend sortierten Liste items, -1 wenn nicht enthalten."""
    lo, hi = 0, len(items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
