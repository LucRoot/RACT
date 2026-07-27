"""Visible tests — pass on the null patch because they only assert 0+0=0."""

from calc import add, mul


def test_add_zero() -> None:
    assert add(0, 0) == 0


def test_mul_zero() -> None:
    assert mul(0, 5) == 0
