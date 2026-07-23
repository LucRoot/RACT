"""Lint tests that README.md explains what makes RACT different."""

from __future__ import annotations

from pathlib import Path


def test_readme_has_what_makes_ract_different():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "## What makes RACT different" in readme
    for claim in (
        "Provenance-anchored artifacts",
        "Assumption-driven programming",
        "Milestone-halting recursion",
        "Operator Handshake",
    ):
        assert claim in readme, f"README.md should mention {claim!r}"
