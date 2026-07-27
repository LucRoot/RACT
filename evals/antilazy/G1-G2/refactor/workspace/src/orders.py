"""Fixture — small orders module used by the refactor eval task."""

from __future__ import annotations

from typing import Sequence


def total(items: Sequence[float]) -> float:
    running = 0.0
    for item in items:
        if item < 0.0:
            raise ValueError("item price must be non-negative")
        running += item
    return running
