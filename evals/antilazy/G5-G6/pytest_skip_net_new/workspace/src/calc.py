"""Fixture module — divide() has a latent bug (no guard on b == 0)."""


def divide(a: int, b: int) -> float:
    return a / b
