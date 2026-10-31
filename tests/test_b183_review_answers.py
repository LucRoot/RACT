"""B-183: every review menu reads its answers the same way; "s"/"skip" leave a change out.

The per-hunk review of a proposed change read "s skip" and typing ``s`` applied the
hunk. Each menu is driven with every answer it lists and with answers it does not.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ract import review_hunks
from ract.review_hunks import ReviewStopped, review_proposed_file

BEFORE = b"x = 1\n"
AFTER = b"x = 2\n"


def _asker(*replies: str | None):  # type: ignore[no-untyped-def]
    queue: Iterator[str | None] = iter(replies)
    asked: list[str] = []

    def ask(question: str) -> str | None:
        asked.append(question)
        return next(queue)

    return ask, asked


@pytest.mark.parametrize(
    ("answer", "applied"),
    [
        ("a", True),
        ("y", True),
        ("yes", True),
        ("Y", True),
        ("r", False),
        ("n", False),
        ("no", False),
        ("s", False),
        ("skip", False),
    ],
)
def test_the_hunk_menu_of_a_proposed_change(answer: str, applied: bool) -> None:
    ask, _ = _asker(answer)
    said: list[str] = []
    decision = review_proposed_file("a.py", BEFORE, AFTER, ask, said.append)
    assert decision.content == (AFTER if applied else BEFORE)


@pytest.mark.parametrize("answer", ["k", "keep", "apply", "ok", "x", "1", ""])
def test_an_answer_outside_the_hunk_menu_changes_nothing_and_asks_again(
    answer: str,
) -> None:
    ask, asked = _asker(answer, "r")
    said: list[str] = []
    decision = review_proposed_file("a.py", BEFORE, AFTER, ask, said.append)
    assert decision.content == BEFORE  # the second answer, "r", left it out
    assert len(asked) == 2
    assert any("Not understood" in line for line in said)


def test_end_of_input_in_the_hunk_menu_is_a_refusal() -> None:
    ask, _ = _asker(None)
    with pytest.raises(ReviewStopped):
        review_proposed_file("a.py", BEFORE, AFTER, ask, lambda line: None)


@pytest.mark.parametrize(
    ("answer", "keep"),
    [
        ("k", True),
        ("keep", True),
        ("a", True),
        ("y", True),
        ("yes", True),
        ("r", False),
        ("restore", False),
        ("n", False),
        ("no", False),
        ("s", False),
        ("skip", False),
    ],
)
def test_the_whole_file_keep_menu(answer: str, keep: bool) -> None:
    ask, _ = _asker(answer)
    assert review_hunks._whole_file("Keep it?", ask, lambda line: None) is keep


@pytest.mark.parametrize(
    ("answer", "apply"),
    [
        ("a", True),
        ("y", True),
        ("yes", True),
        ("apply", True),
        ("r", False),
        ("n", False),
        ("no", False),
        ("s", False),
        ("skip", False),
    ],
)
def test_the_whole_file_apply_menu(answer: str, apply: bool) -> None:
    ask, _ = _asker(answer)
    assert review_hunks._apply_whole("Apply it?", ask, lambda line: None) is apply


@pytest.mark.parametrize("menu", [review_hunks._whole_file, review_hunks._apply_whole])
@pytest.mark.parametrize("answer", ["k?", "x", "1", "maybe", ""])
def test_a_whole_file_menu_says_when_it_does_not_understand(menu, answer: str) -> None:  # type: ignore[no-untyped-def]
    ask, asked = _asker(answer, "r")
    said: list[str] = []
    assert menu("Question?", ask, said.append) is False
    assert len(asked) == 2 and any("Not understood" in line for line in said)


@pytest.mark.parametrize("menu", [review_hunks._whole_file, review_hunks._apply_whole])
def test_end_of_input_in_a_whole_file_menu_is_a_refusal(menu) -> None:  # type: ignore[no-untyped-def]
    ask, _ = _asker(None)
    with pytest.raises(ReviewStopped):
        menu("Question?", ask, lambda line: None)


def test_the_menu_says_what_skip_does() -> None:
    assert "s skip (leave it out)" in review_hunks.CHOICES
