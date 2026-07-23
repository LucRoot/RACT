"""Tests for README CLI verb index."""

from __future__ import annotations


from pathlib import Path


def test_readme_contains_cli_verb_index():
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "## CLI Verb Index" in text
    assert "ract doctor" in text
    assert "ract config validate" in text
    assert "ract provider health" in text
    assert "ract session list" in text
    assert "ract plan diff" in text


# RACT 0.1.1 - Trust and tooling
