"""B-048: the session guide's samples come from captures, and its commands exist.

The guide copies each sample from a capture under docs/ux/guide, so a sample
cannot be typed in by hand. These tests check that, plus the commands, the links
and the wording rules.
"""

from __future__ import annotations

import re
from pathlib import Path

from ract.repl import HELP_ROWS

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "SESSION_GUIDE.md"
CAPTURES = ROOT / "docs" / "ux" / "guide"
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
LINK = re.compile(r"\]\(([^)#\s]+)\)")
CONTRAST = re.compile(r"\bnot [^.,;]{1,40}, but\b", re.I)


def _blocks() -> list[str]:
    return [
        m.group(1).rstrip("\n")
        for m in FENCE.finditer(GUIDE.read_text(encoding="utf-8"))
    ]


def test_every_slash_command_in_the_guide_is_in_the_help_table():
    help_names = {row[0].split()[0] for row in HELP_ROWS if row[0].startswith("/")}
    seen = set()
    for block in _blocks():
        seen.update(re.findall(r"(?m)^\s*(/[a-z][\w-]*)", block))
    assert seen <= help_names, sorted(seen - help_names)


def test_every_linked_file_exists():
    for target in LINK.findall(GUIDE.read_text(encoding="utf-8")):
        if target.startswith("http"):
            continue
        assert (GUIDE.parent / target).exists(), target


def test_no_em_dash_and_no_contrast_construction():
    text = GUIDE.read_text(encoding="utf-8")
    assert "—" not in text
    assert not CONTRAST.search(text), CONTRAST.search(text).group(0)


def test_every_sample_is_a_substring_of_a_capture():
    captures = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(CAPTURES.glob("*.txt"))
    )
    blocks = _blocks()
    assert blocks, "the guide has no sample blocks"
    for block in blocks:
        assert block in captures, block[:80]


def test_each_capture_says_how_it_was_made():
    for path in sorted(CAPTURES.glob("*.txt")):
        head = path.read_text(encoding="utf-8").splitlines()[:3]
        assert head[0].startswith("# Captured:"), path.name
        assert any("fake server" in line for line in head), path.name
