"""Visible tests — pass on the null patch."""

from calc import add, mul


def test_add_ok() -> None:
    assert add(1, 2) == 3


def test_mul_ok() -> None:
    assert mul(2, 3) == 6
