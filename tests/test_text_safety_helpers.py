"""L-141 decision 1: one rule for direction marks, and one escaped form for decisions.

`safe_text` (every screen, streamed replies included) replaces the Unicode
direction marks and overrides like other control characters. `visible_text`
(repository and server text the operator reads to decide) shows them, and the
control characters, as visible escapes. `trust.visible` is the same function.
"""

from __future__ import annotations

import pytest

from ract import trust
from ract.session_events import safe_text, visible_text

MARKS = [0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)]
REPLACEMENT = chr(0xFFFD)


@pytest.mark.parametrize("code", MARKS, ids=lambda c: f"U+{c:04X}")
def test_safe_text_replaces_every_direction_mark(code: int) -> None:
    text = "abc" + chr(code) + "def"

    out = safe_text(text)

    assert chr(code) not in out
    assert out == "abc" + REPLACEMENT + "def"


@pytest.mark.parametrize("code", MARKS, ids=lambda c: f"U+{c:04X}")
def test_visible_text_shows_every_direction_mark_escaped(code: int) -> None:
    out = visible_text("x" + chr(code) + "y")

    assert chr(code) not in out
    assert out == "x" + "\\u" + f"{code:04x}" + "y"


def test_safe_text_keeps_what_it_kept() -> None:
    # B-045: a carriage return is dropped; newlines and tabs stay.
    assert safe_text("a\r\nb\tc") == "a\nb\tc"
    assert safe_text("x" + chr(0x1B) + "[2J") == "x" + REPLACEMENT + "[2J"


def test_visible_text_escapes_controls_and_keeps_backslashes() -> None:
    assert visible_text("a\rb\nc\td" + chr(0x1B)) == "a\\rb\\nc\\td\\x1b"
    assert visible_text("C:\\tools\\x.exe") == "C:\\tools\\x.exe"


def test_the_trust_prompt_uses_the_shared_helper() -> None:
    assert trust.visible is visible_text
