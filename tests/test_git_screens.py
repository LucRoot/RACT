"""B-126 screens: the commit prompt with its secret-scan result, the branch and worktree prompts,
and the push prompt that names the handshake (ADR-0048 D8). Pure text at 80, 60 and 40 columns.
A staged secret blocks the commit with no yes; the model's message is labeled as the model's.
"""

from __future__ import annotations

import pytest

from ract.ui.git_screens import (
    BRANCH_CHOICES,
    COMMIT_CHOICES,
    CommitRequest,
    SecretFinding,
    branch_prompt_lines,
    commit_prompt_lines,
    push_prompt_lines,
    worktree_prompt_lines,
)

WIDTHS = (80, 60, 40)


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(lines).split())


@pytest.mark.parametrize("width", WIDTHS)
def test_a_clean_commit_shows_the_files_the_message_and_the_passed_scan(
    width: int,
) -> None:
    req = CommitRequest(
        message="fix add()", files=("src/calc.py", "tests/test_calc.py")
    )
    lines = commit_prompt_lines(req, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "commit (tier 2)" in text
    assert "files: 2" in text and "src/calc.py" in text
    assert "message (the model wrote this text): fix add()" in text
    assert "secret scan: passed (2 files)" in text
    assert " ".join(COMMIT_CHOICES.split()) in text


@pytest.mark.parametrize("width", WIDTHS)
def test_a_staged_secret_blocks_the_commit_with_no_yes(width: int) -> None:
    req = CommitRequest(
        message="add config",
        files=(".env",),
        findings=(SecretFinding(path=".env", kind="api key shape"),),
    )
    lines = commit_prompt_lines(req, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "secret scan: blocked; the commit is refused" in text
    assert ".env: api key shape" in text
    assert "[y]es" not in text


def test_a_control_character_in_the_message_is_visible() -> None:
    req = CommitRequest(message="fix\x1b[31m", files=("a.py",))
    text = "\n".join(commit_prompt_lines(req, 80))
    assert "\x1b" not in text and "\\x1b" in text


@pytest.mark.parametrize("width", WIDTHS)
def test_branch_and_worktree_prompts_fit_and_say_what_they_do(width: int) -> None:
    lines = branch_prompt_lines("create", "feature-x", width) + worktree_prompt_lines(
        "../wt", width
    )
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "create branch feature-x" in text
    assert "add a worktree at ../wt" in text
    assert " ".join(BRANCH_CHOICES.split()) in text


@pytest.mark.parametrize("width", WIDTHS)
def test_the_push_prompt_is_tier_three_and_names_the_handshake(width: int) -> None:
    lines = push_prompt_lines("origin", "main", width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "push (tier 3, remote git)" in text
    assert "push main to origin" in text
    assert "this needs a handshake" in text
    assert "[n]o, do not push" in text
