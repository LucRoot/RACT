"""Lint tests that README.md stays in sync with the released version and CLI surface."""

from __future__ import annotations

from pathlib import Path

from rootact import __version__


def test_readme_mentions_current_version():
    """README.md must mention the current RACT version."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert __version__ in text, (
        f"README.md should mention the current version {__version__}"
    )


def test_readme_verb_index_includes_core_verbs():
    """The CLI verb index must include the core verbs shipped in v0.2.0."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    for verb in (
        "`ract doctor`",
        "`ract config validate`",
        "`ract provider health`",
        "`ract session list`",
        "`ract plan diff`",
        "`ract run`",
        "`ract fence`",
    ):
        assert verb in text, f"README.md CLI verb index should include {verb}"
