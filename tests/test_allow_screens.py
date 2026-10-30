"""B-113 screens: the allow-rule line, the session approvals, and the entry-point question
(ADR-0048 D4 and D6, G-214). Pure text at 80, 60 and 40 columns, plain and rich. Nothing may
carry a raw escape sequence; NO_COLOR output is the plain output.
"""

from __future__ import annotations

import re

import pytest

from ract.ui.allow_screens import (
    CARRY_STATEMENT,
    ENTRY_CHOICES,
    AllowRule,
    EntryPointChange,
    SessionApproval,
    allowed_by_rule_lines,
    entry_point_question_lines,
    escape_controls,
    session_approvals_lines,
)

WIDTHS = (80, 60, 40)
MARKUP = re.compile(r"\[/?bold\]")


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(MARKUP.sub("", line) for line in lines).split())


RULE = AllowRule(rule_id="R-7", prefix=("python", "-m", "pytest"))


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_allow_line_names_the_rule_and_its_prefix(width: int, rich: bool) -> None:
    lines = allowed_by_rule_lines(
        ("python", "-m", "pytest", "tests/"), RULE, width, rich=rich
    )
    for line in lines:
        assert len(MARKUP.sub("", line)) <= width, line
    text = _flat(lines)
    assert "ran without asking: an allow rule matches" in text
    assert "argv: python -m pytest tests/" in text
    assert "rule R-7: prefix python -m pytest" in text
    assert "tier 2 and the always-ask list still ask" in text


@pytest.mark.parametrize("width", WIDTHS)
def test_no_approvals_says_so(width: int) -> None:
    lines = session_approvals_lines([], width)
    assert _flat(lines) == "no approvals this session"


@pytest.mark.parametrize("width", WIDTHS)
def test_each_session_approval_is_listed_and_the_carry_rule_stated(width: int) -> None:
    lines = session_approvals_lines(
        [
            SessionApproval(prefix=("python", "-m", "pytest")),
            SessionApproval(prefix=("git", "status"), scope="this step only"),
        ],
        width,
    )
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "python -m pytest: this session" in text
    assert "git status: this step only" in text
    assert CARRY_STATEMENT in text


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_entry_point_question_names_the_file_the_reason_and_the_choices(
    width: int, rich: bool
) -> None:
    lines = entry_point_question_lines(
        EntryPointChange(
            path="tests/conftest.py", reason="written by the model this session"
        ),
        width,
        rich=rich,
    )
    for line in lines:
        assert len(MARKUP.sub("", line)) <= width, line
    text = _flat(lines)
    assert "this file runs your tests and it changed" in text
    assert "file: tests/conftest.py" in text
    assert "why it asks now: written by the model this session" in text
    assert "an allow rule does not answer for it" in text
    assert " ".join(ENTRY_CHOICES.split()) in text


def test_the_entry_point_reason_can_say_changed_since_the_grant() -> None:
    text = _flat(
        entry_point_question_lines(
            EntryPointChange(
                path="pytest.ini", reason="changed since the grant was signed"
            ),
            80,
        )
    )
    assert "changed since the grant was signed" in text


def test_bold_only_in_rich_output() -> None:
    plain = entry_point_question_lines(EntryPointChange(path="a.py", reason="r"), 80)
    rich = entry_point_question_lines(
        EntryPointChange(path="a.py", reason="r"), 80, rich=True
    )
    assert not any("[bold]" in line for line in plain)
    assert any("[bold]" in line for line in rich)


def test_escape_sequences_in_paths_and_argv_are_shown_escaped() -> None:
    lines = entry_point_question_lines(
        EntryPointChange(path="evil\x1b[31m.py‮", reason="changed\x07"), 40
    )
    joined = "\n".join(lines)
    assert "\x1b" not in joined and "\x07" not in joined and "‮" not in joined
    assert "\\x1b" in joined and "\\u202e" in joined and "\\x07" in joined
    rule_lines = allowed_by_rule_lines(("bad\x1b",), AllowRule("R", ("bad\x1b",)), 40)
    assert not any("\x1b" in line for line in rule_lines)


def test_escape_controls_keeps_plain_text() -> None:
    assert escape_controls("tests/test_calc.py") == "tests/test_calc.py"
    assert escape_controls("a\tb") == "a\\tb"
