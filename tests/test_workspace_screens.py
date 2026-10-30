"""B-110 screens: diff.proposed, the apply result, /checkpoint, /restore, the preparing line and
the not-a-git offer (ADR-0047 D6). Pure text, checked at 80, 60 and 40 columns, plain and rich.
Every line fits the width; a path or a line with an escape sequence is shown escaped.
"""

from __future__ import annotations

import re

import pytest

from ract.ui.workspace_screens import (
    ApplyResult,
    Checkpoint,
    FileProposal,
    Hunk,
    apply_result_lines,
    checkpoint_lines,
    diff_proposed_lines,
    hunk_id,
    not_git_offer_lines,
    preparing_line,
    restore_preview_lines,
)

WIDTHS = (80, 60, 40)
MARKUP = re.compile(r"\[/?bold\]")


def _flat(lines: list[str]) -> str:
    """The lines as one string with single spaces, so a fold inside a phrase does not matter."""
    return " ".join(" ".join(lines).split())


def _plain(lines: list[str]) -> list[str]:
    return [MARKUP.sub("", line) for line in lines]


def _proposal() -> list[FileProposal]:
    hunk = Hunk(
        id=hunk_id("src/calc.py", 1),
        old_start=1,
        old_count=2,
        new_start=1,
        new_count=2,
        lines=("-    return a - b", "+    return a + b", "     pass"),
    )
    return [FileProposal(path="src/calc.py", hunks=(hunk,))]


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_proposal_fits_and_names_each_hunk(width: int, rich: bool) -> None:
    lines = diff_proposed_lines(_proposal(), width, rich=rich)
    for line in _plain(lines):
        assert len(line) <= width, line
    text = _flat(_plain(lines))
    assert "src/calc.py#1" in text
    assert "+1 -1" in text
    assert "+ return a + b" in text


def test_hunk_headers_are_bold_only_in_rich_output() -> None:
    plain = diff_proposed_lines(_proposal(), 80)
    rich = diff_proposed_lines(_proposal(), 80, rich=True)
    assert not any("[bold]" in line for line in plain)
    assert any(line.startswith("[bold]") for line in rich)


@pytest.mark.parametrize("width", WIDTHS)
def test_apply_result_counts_and_saved_patch_paths(width: int) -> None:
    result = ApplyResult(
        applied_hunks=2,
        applied_files=1,
        skipped=("src/other.py",),
        session="s-1",
    )
    lines = apply_result_lines(result, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "applied 2 hunks in 1 file" in text
    assert "skipped src/other.py" in text
    assert ".ract/pending/s-1/" in text


def test_a_single_hunk_is_singular() -> None:
    lines = apply_result_lines(ApplyResult(applied_hunks=1, applied_files=1), 80)
    assert lines[0].startswith("applied 1 hunk in 1 file")


@pytest.mark.parametrize("width", WIDTHS)
def test_checkpoints_are_newest_first_and_mark_the_undone_ones(width: int) -> None:
    # The session's numbering: 1 is the newest, the number /restore N takes.
    lines = checkpoint_lines(
        [
            Checkpoint(
                number=1,
                when="10:05",
                turn="t-2",
                files=3,
                undone=True,
                names=("a.py", "b.py", "c.py"),
            ),
            Checkpoint(number=2, when="10:00", turn="t-1", files=1, names=("a.py",)),
        ],
        width,
    )
    for line in lines:
        assert len(line) <= width, line
    assert lines[0].startswith("1. ") and "(undone)" in lines[0]
    assert lines[-1].startswith("2. ") and "(undone)" not in lines[-1]
    assert "1 file: a.py" in " ".join(lines)


def test_no_checkpoint_says_so() -> None:
    assert checkpoint_lines([], 80) == [
        "no checkpoints yet: a turn that changes a file makes one"
    ]


@pytest.mark.parametrize("width", WIDTHS)
def test_restore_preview_names_what_is_left_alone(width: int) -> None:
    lines = restore_preview_lines(
        4, restore=["src/calc.py"], left_alone=["src/other.py"], width=width
    )
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "back src/calc.py" in text
    assert "left alone src/other.py" in text and "checkpoint 4" in text


def test_the_preparing_line_is_one_line_within_the_width() -> None:
    for width in WIDTHS:
        line = preparing_line(2.4, width)
        assert "\n" not in line and len(line) <= width
        assert line.startswith("preparing a workspace (2 s)")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_not_git_offer_shows_the_exact_command_and_the_choices(
    width: int, rich: bool
) -> None:
    lines = not_git_offer_lines(
        "git init && git add -A && git commit -m 'initial commit'",
        left_out=[".env"],
        width=width,
        rich=rich,
    )
    plain = _plain(lines)
    for line in plain:
        assert len(line) <= width, line
    text = _flat(plain)
    assert "not a git repository" in text
    assert "git init" in text and "initial commit" in text
    assert ".env" in text
    assert "[y]es" in text and "[n]o" in text


def test_a_path_with_an_escape_sequence_is_shown_escaped() -> None:
    bad = [
        FileProposal(
            path="evil\x1b[31m.py",
            hunks=(
                Hunk(
                    id=hunk_id("evil.py", 1),
                    old_start=1,
                    old_count=0,
                    new_start=1,
                    new_count=1,
                    lines=("+x",),
                ),
            ),
        )
    ]
    lines = diff_proposed_lines(bad, 80)
    assert not any("\x1b" in line for line in lines)
    result = apply_result_lines(
        ApplyResult(
            applied_hunks=0, applied_files=0, skipped=("evil\x1b.py",), session="s"
        ),
        80,
    )
    assert not any("\x1b" in line for line in result)
