"""Fixture — new function added, no tests exercising it."""

from typing import Sequence


def mean(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("mean of empty sequence")
    return sum(xs) / len(xs)


def median(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("median of empty sequence")
    ordered = sorted(xs)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0
