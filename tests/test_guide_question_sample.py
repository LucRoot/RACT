"""Adjudication row 4 and B-100: the guide's question sample is copied from its capture.

The sample is a block of the guide that must match the capture file line for line. The
capture runs /ask through the read-only loop (B-010a, B-011a), so the section must say that
the fake server wrote the answer, must name the file the model read, and must not describe
an open defect.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _question_section() -> str:
    guide = (ROOT / "docs" / "SESSION_GUIDE.md").read_text(encoding="utf-8")
    return guide.split("## A question that completes", 1)[1].split(
        "## Mode, cost and undo", 1
    )[0]


def _question_block() -> list[str]:
    fenced = _question_section().split("```text", 1)[1].split("```", 1)[0]
    return fenced.strip("\n").split("\n")


def test_the_question_sample_is_copied_from_the_capture():
    capture = (
        (ROOT / "docs" / "ux" / "guide" / "ask_read_calc.txt")
        .read_text(encoding="utf-8")
        .split("\n")
    )
    block = _question_block()
    start = capture.index(block[0])
    assert capture[start : start + len(block)] == block


def test_the_question_section_marks_the_fake_server_and_the_file_read():
    section = _question_section()
    assert "fake server wrote it" in section
    assert "src/calc.py" in section
    assert "read_file(" in "\n".join(_question_block())


def test_the_question_section_describes_no_open_defect():
    section = _question_section().lower()
    assert "defect" not in section
    assert "raw json" not in section
    assert "stays open" not in section
