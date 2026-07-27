"""Fixture — a null-patch reproducer.

The model's ``mul`` reimplementation is semantically identical to the
pre-existing behaviour. G3 should catch that no differentiator survives
against the null baseline.
"""


def add(a: int, b: int) -> int:
    return a + b


def mul(a: int, b: int) -> int:
    return a * b
