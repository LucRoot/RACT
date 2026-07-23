"""Tests for the RACT security best practices guide."""

from __future__ import annotations


import re
from pathlib import Path


def test_security_best_practices_guide():
    guide = Path(__file__).parent.parent / "docs" / "security_best_practices.md"
    assert guide.exists()
    content = guide.read_text(encoding="utf-8")

    h2_sections = re.findall(r"^##\s+(.+)$", content, re.MULTILINE)
    assert len(h2_sections) >= 4, f"only {len(h2_sections)} H2 sections"

    code_blocks = re.findall(r"```\w*\n(.*?)```", content, re.DOTALL)
    assert code_blocks, "no code blocks found"

    for section in [
        "provider keys",
        "load-bearing",
        "receipts",
        "novelty",
    ]:
        assert any(section.lower() in s.lower() for s in h2_sections), section
