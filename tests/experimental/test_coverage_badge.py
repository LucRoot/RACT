# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for ract.coverage_badge."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from ract.experimental.coverage_badge import generate_svg


def test_generate_svg_creates_file(tmp_path):
    output = tmp_path / "badge.svg"
    result = generate_svg(85, output)
    assert result == output
    text = output.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "coverage" in text
    assert "85%" in text


def test_generate_svg_colors(tmp_path):
    green = tmp_path / "green.svg"
    yellow = tmp_path / "yellow.svg"
    red = tmp_path / "red.svg"
    generate_svg(85, green)
    generate_svg(65, yellow)
    generate_svg(40, red)
    assert "#4c1" in green.read_text(encoding="utf-8")
    assert "#dfb317" in yellow.read_text(encoding="utf-8")
    assert "#e05d44" in red.read_text(encoding="utf-8")


# RACT 0.1.2 - Trust and tooling
