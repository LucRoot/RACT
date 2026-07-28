"""Fixture — a solution-leakage reproducer.

The retrieval-index adapter and git-history search both surface the
same block below when the leakage check runs against the claimed patch,
because the hunk clears the 5-line / 100-char floor.
"""

from datetime import date


def format_datestamp(d: date) -> str:
    year = f"{d.year:04d}"
    month = f"{d.month:02d}"
    day = f"{d.day:02d}"
    return f"{year}-{month}-{day}"
