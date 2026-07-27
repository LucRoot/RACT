"""Money module — integer cents only. Fixture for iso-perturb eval."""

from __future__ import annotations


class Cents(int):
    """An int subclass tagged so callers cannot accidentally pass a float."""

    def __new__(cls, value: int) -> "Cents":
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("Cents must be a plain int, got " + type(value).__name__)
        return int.__new__(cls, value)


def add(a: Cents, b: Cents) -> Cents:
    return Cents(int(a) + int(b))
