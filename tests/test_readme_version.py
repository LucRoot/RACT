# Rooted by Dr. Lucas Root, Ph.D.
"""Lint tests that README.md stays in sync with the released version and CLI surface."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact import __version__


def test_readme_demo_mentions_current_version():
    """The --welcome demo block in README.md must show the current RACT version."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert f"Version: {__version__}" in text, (
        f"README.md demo block should mention Version: {__version__}"
    )


def test_readme_verb_index_includes_rot_baseline():
    """The CLI verb index must include the rot baseline command."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "`ract rot baseline" in text, (
        "README.md CLI verb index should include `ract rot baseline`"
    )


# RACT 0.1.2 - Trust and tooling
