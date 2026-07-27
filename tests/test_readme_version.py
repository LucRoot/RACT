"""Lint tests that README.md stays in sync with the released version and CLI surface."""

from __future__ import annotations

from pathlib import Path

from ract import __version__


def test_readme_mentions_current_version():
    """README.md must mention the current RACT version. Accepts either the
    canonical PEP 440 form (``0.4.0rc1``) or the display-friendly
    hyphenated form (``0.4.0-rc1``); both resolve to the same PEP 440
    identity under ``packaging.version.Version``."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    hyphenated = __version__.replace("rc", "-rc")  # 0.4.0rc1 -> 0.4.0-rc1
    assert __version__ in text or hyphenated in text, (
        f"README.md should mention the current version "
        f"{__version__} (or its display form {hyphenated})"
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
        "`ract fence inspect --file <path>`",
    ):
        assert verb in text, f"README.md CLI verb index should include {verb}"
