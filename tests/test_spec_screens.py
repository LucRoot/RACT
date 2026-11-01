"""B-178 first slice: the spec screens are pure text, fit 80, 60 and 40 columns, and show escapes for control characters."""

from __future__ import annotations

import pytest

from ract.ui.spec_screens import (
    APPROVAL_CHOICES,
    QUESTIONS,
    SECTIONS,
    approval_lines,
    check_lines,
    question_lines,
    saved_lines,
)

WIDTHS = (80, 60, 40)
FULL_DIGEST = "ab" * 32


def test_there_are_six_questions_and_six_sections_in_order() -> None:
    assert len(QUESTIONS) == 6
    assert SECTIONS == (
        "Goal",
        "Users",
        "Must do",
        "Must not do",
        "How we will know",
        "Limits",
    )


@pytest.mark.parametrize("width", WIDTHS)
def test_every_question_screen_fits_and_shows_its_number(width: int) -> None:
    for index, (question, example) in enumerate(QUESTIONS, start=1):
        lines = question_lines(index, question, example, width)
        assert all(len(line) <= width for line in lines), lines
        assert lines[0] == f"question {index} of 6"


@pytest.mark.parametrize("width", WIDTHS)
def test_the_approval_screen_fits_and_offers_the_three_choices(width: int) -> None:
    body = "The tool counts words in one file and prints the count. " * 3
    lines = approval_lines("Goal", body, width)
    assert all(len(line) <= width for line in lines), lines
    assert lines[0] == "section: Goal"
    assert " ".join(APPROVAL_CHOICES.split()) in " ".join(" ".join(lines).split())


def test_a_clean_check_says_so() -> None:
    assert check_lines([], [], 80) == [
        "every section is here, and each acceptance line can be checked"
    ]


@pytest.mark.parametrize("width", WIDTHS)
def test_a_missing_section_and_an_uncheckable_line_are_named(width: int) -> None:
    lines = check_lines(["Limits"], [("How we will know", "it is fast")], width)
    assert all(len(line) <= width for line in lines), lines
    text = " ".join(" ".join(lines).split())
    assert "missing section: Limits" in text
    assert 'not checkable in How we will know: "it is fast"' in text
    assert "prints" in text and "counts" in text


def test_the_saved_line_shows_the_hash_prefix_and_never_the_whole_digest() -> None:
    line = " ".join(saved_lines("SPEC.md", FULL_DIGEST, 80))
    assert "sha256 abababababab..." in line
    assert FULL_DIGEST not in line


def test_control_characters_in_a_draft_are_shown_as_escapes() -> None:
    lines = approval_lines("Goal", "a\x1b[31mred\x07 goal", 80)
    text = "\n".join(lines)
    assert "\x1b" not in text and "\x07" not in text
    assert "\\x1b" in text and "\\x07" in text
