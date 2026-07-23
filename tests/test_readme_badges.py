# Rooted by Dr. Lucas Root, Ph.D.
"""Tests that README.md carries badges and a Quickstart section."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from pathlib import Path


def test_readme_has_badge_section():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "![RootAct CI]" in readme
    assert "![Coverage]" in readme
    assert "![License]" in readme
    assert "![Python]" in readme


def test_readme_has_quickstart_with_core_commands():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "## Quickstart" in readme
    assert "ract run" in readme
    assert "ract doctor" in readme
    assert "ract fence" in readme


def test_readme_demo_embed_link():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert re.search(r"\[\!\[asciicast\]\([^)]+\)\]\([^)]+\)", readme)
