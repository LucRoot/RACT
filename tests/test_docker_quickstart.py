# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RACT Docker quickstart guide."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from pathlib import Path


def test_docker_quickstart_guide():
    guide = Path(__file__).parent.parent / "docs" / "docker.md"
    assert guide.exists()
    content = guide.read_text(encoding="utf-8")

    h2_sections = re.findall(r"^##\s+(.+)$", content, re.MULTILINE)
    assert len(h2_sections) >= 4, f"only {len(h2_sections)} H2 sections"

    code_blocks = re.findall(r"```\w*\n(.*?)```", content, re.DOTALL)
    assert any("docker" in block.lower() for block in code_blocks), (
        "no docker code block"
    )
