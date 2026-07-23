# Rooted by Dr. Lucas Root, Ph.D.
"""Tests that README.md carries the Why RACT comparison table."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path


def test_readme_has_why_ract_comparison_table():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "## Why RACT instead of Cursor, Claude Code, or Lovable?" in readme
    assert "| Dimension | RACT | Cursor | Claude Code | Lovable |" in readme
    assert "**Pricing model**" in readme
    for name in ("RACT", "Cursor", "Claude Code", "Lovable"):
        assert name in readme
