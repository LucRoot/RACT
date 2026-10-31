"""B-183: every review menu reads its answers the same way.

The per-hunk review of a proposed change read "s skip" and typing ``s`` applied the
hunk. "s"/"skip" now makes no change to what is on disk (G-287): in the post-turn
``/review`` the hunk stays as the turn left it; in the proposed review it is not
applied. Each menu is driven with every answer it lists and with answers it does not,
and the hunk menu on both screens with the file bytes that result.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from ract import review_hunks
from ract.review_hunks import ReviewStopped, review_proposed_file
from tests.test_repl import _session
from tests.test_undo import _turn

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
    assert any("s skip (do not apply it)" in line for line in said)


@pytest.mark.parametrize(
    ("answer", "kept"),
    [
        ("a", True),
        ("y", True),
        ("yes", True),
        ("Y", True),
        ("s", True),
        ("skip", True),
        ("r", False),
        ("n", False),
        ("no", False),
    ],
)
def test_the_hunk_menu_of_the_applied_review(
    tmp_path: Path, answer: str, kept: bool
) -> None:
    # The turn's change is on disk: "s" leaves it there, "r" restores the saved copy.
    (tmp_path / "a.py").write_bytes(BEFORE)
    _turn(tmp_path, {"a.py": AFTER.decode("utf-8")})
    session, _, console = _session([answer], config=tmp_path / "ract.yaml")
    session.handle("/review")
    on_disk = (tmp_path / "a.py").read_bytes().replace(b"\r\n", b"\n")
    assert on_disk == (AFTER if kept else BEFORE)
    assert "s skip (leave it as it is)" in console.text


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
        ("s", True),
        ("skip", True),
        ("r", False),
        ("restore", False),
        ("n", False),
        ("no", False),
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
        ("k", True),
        ("keep", True),
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


def test_the_menu_says_what_skip_does_on_each_screen() -> None:
    assert "s skip (leave it as it is)" in review_hunks.choice_items(True)
    assert "s skip (do not apply it)" in review_hunks.choice_items(False)
    assert review_hunks.CHOICE_ITEMS == review_hunks.choice_items(True)
