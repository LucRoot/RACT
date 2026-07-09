# Rooted by Dr. Lucas Root, Ph.D.
"""Sanity checks for the Hugging Face Space static landing page."""

from __future__ import annotations

from pathlib import Path


def _hf_space_dir() -> Path:
    return Path(__file__).parent.parent / "assets" / "hf-space"


def test_hf_space_index_exists():
    """The landing page must exist."""
    index = _hf_space_dir() / "index.html"
    assert index.is_file()


def test_hf_space_index_has_required_sections():
    """The landing page must cover the key RACT selling points."""
    html = (_hf_space_dir() / "index.html").read_text(encoding="utf-8")
    required = [
        "RACT",
        "anti-rot",
        "consolidate",
        "novelty",
        "auction",
        "fence",
        "Quick start",
        "GitHub",
    ]
    for token in required:
        assert token in html, f"missing section: {token}"


def test_hf_space_readme_exists():
    """Deployment instructions must exist."""
    assert (_hf_space_dir() / "README.md").is_file()


# RACT 0.1.1 - Trust and Tooling
