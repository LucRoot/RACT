# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for CHANGELOG.md."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path


def test_changelog_contains_release_notes():
    changelog = Path(__file__).parent.parent / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    assert "# Changelog" in text
    assert "## 0.1.2" in text
    assert "Signed receipts" in text
    assert "CLI verbs" in text


# RACT 0.1.1 - Trust and tooling
