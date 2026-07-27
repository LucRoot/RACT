"""Fixture — CSV line parser (skeleton). Task: implement parse_csv_line."""

from __future__ import annotations


def parse_csv_line(line: str) -> tuple[str, ...]:
    """Return the comma-separated fields of ``line`` as a tuple.

    Skeleton implementation — the eval task exercises whether the
    completed function is measured by the mutation-kill gate.
    """
    return tuple(line.split(","))
