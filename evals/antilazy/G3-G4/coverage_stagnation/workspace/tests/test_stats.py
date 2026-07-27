"""Fixture — only ``mean`` is covered. ``median`` is not touched by tests."""

from stats import mean


def test_mean_ok() -> None:
    assert mean([2, 4, 6]) == 4
