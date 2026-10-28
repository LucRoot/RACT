"""Adjudication row 4: the guide's question sample is copied from its capture.

The sample is a block of the guide that must match the capture file line for line,
and the guide must still say that the fake server wrote the answer and that /ask
prints a plan and raw JSON (the defect that stays open until B-010a and B-011a).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _question_block() -> list[str]:
    guide = (ROOT / "docs" / "SESSION_GUIDE.md").read_text(encoding="utf-8")
    section = guide.split("## A question that completes", 1)[1].split(
        "## Mode, cost and undo", 1
    )[0]
    fenced = section.split("```text", 1)[1].split("```", 1)[0]
    return [line for line in fenced.strip("\n").split("\n")]


def test_the_question_sample_is_copied_from_the_capture():
    capture = (
        (ROOT / "docs" / "ux" / "guide" / "ask_calc_answer.txt")
        .read_text(encoding="utf-8")
        .split("\n")
    )
    block = _question_block()
    start = capture.index(block[0])
    assert capture[start : start + len(block)] == block


def test_the_question_section_still_marks_the_fake_server_and_the_defect():
    guide = (ROOT / "docs" / "SESSION_GUIDE.md").read_text(encoding="utf-8")
    section = guide.split("## A question that completes", 1)[1].split(
        "## Mode, cost and undo", 1
    )[0]
    assert "fake server wrote it" in section
    assert "prints a plan first" in section and "raw JSON" in section
