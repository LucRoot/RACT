"""Fixture — build_summary is the downstream caller G6 must catch."""

from src.billing import total


def build_summary(items: list[float]) -> str:
    return f"total = {total(items)}"
