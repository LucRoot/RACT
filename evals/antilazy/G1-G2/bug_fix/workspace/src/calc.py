"""Fixture — buggy `add`. The visible suite passes on the null patch."""

def add(a: int, b: int) -> int:
    return a - b  # bug: should be a + b


def mul(a: int, b: int) -> int:
    return a * b
