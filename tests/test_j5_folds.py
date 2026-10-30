"""J5 defects 1 and 2 (MASON's B-117 walk): fold between items, never inside one.

The status line folded inside "T3 off" at 60 columns, and the review's
choice prompt folded in the middle of "R reject the rest of the file".
"""

from __future__ import annotations

import io

import pytest

from ract.review_hunks import CHOICE_ITEMS, choice_lines
from ract.session_events import SessionEvent
from ract.session_render import PlainRenderer


@pytest.mark.parametrize("width", [20, 37, 40, 57, 60, 77, 80])
def test_the_review_choices_fold_at_the_commas(width: int) -> None:
    lines = choice_lines(width)
    joined = " ".join(lines)
    for item in CHOICE_ITEMS:
        assert any(item in line for line in lines), (item, lines)
    assert joined.count(",") == len(CHOICE_ITEMS) - 1
    for line in lines:
        assert len(line) <= max(width, len(max(CHOICE_ITEMS, key=len)) + 1), line


def _status(width: int, model: str) -> list[str]:
    out = io.StringIO()
    renderer = PlainRenderer(out.write, width=width, wrap=True)
    renderer(
        SessionEvent(
            seq=1,
            t="",
            session="s",
            turn=None,
            kind="session.started",
            data={
                "model": model,
                "provider": "local",
                "branch": "master",
                "mode": "default",
                "tier3": "off",
            },
        )
    )
    return out.getvalue().splitlines()


@pytest.mark.parametrize("width", [40, 60])
def test_the_status_line_folds_between_items(width: int) -> None:
    lines = _status(width, "qwen-coder-32b-instruct-q4")
    assert any("T3 off" in line for line in lines), lines
    for line in lines:
        assert len(line) <= width, line
        assert not line.strip().startswith("off")


def test_a_status_line_that_fits_is_one_line() -> None:
    assert _status(80, "fake-coder") == [
        "RACT session fake-coder via local | master | default | T3 off"
    ]
