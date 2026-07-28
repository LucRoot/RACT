"""Tests that README.md carries badges and a Quickstart section."""

from __future__ import annotations


from pathlib import Path


def test_readme_has_badge_section():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "![RACT CI]" in readme
    assert "![Coverage]" in readme
    assert "![License]" in readme
    assert "![Python]" in readme


def test_readme_has_quickstart_with_core_commands():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "## Quickstart" in readme
    assert "ract run" in readme
    assert "ract doctor" in readme
    assert "ract fence" in readme
