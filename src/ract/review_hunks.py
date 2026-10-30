"""Review the last turn's change hunk by hunk: ``/review`` (B-014c).

After a turn changed files, the user takes each hunk as it is (accept or
skip), puts back the turn's saved copy of it (reject), or types new lines
for it (edit). The hunks are the groups ``diff_render`` draws, so they are
the hunks the turn summary showed. A rejected hunk is restored from the
turn's saved copy; a file whose every hunk is rejected gets the saved bytes
back exactly, and a file the turn created is removed again.

``/undo`` stays true: after a file is rewritten here, the turn's manifest
records its new contents (``undo_backup.note_reviewed``), so ``/undo`` still
restores the saved copy rather than skipping the file as edited since.
The texts are hostile: every line shown goes through ``safe_text``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ract import diff_render, undo_backup
from ract.session_events import safe_text
from ract.workspace_path import WorkspacePathRefused, require_workspace_path

# An answer for one hunk: True keeps the turn's text, False puts the saved
# text back, a list of lines replaces the turn's text with what was typed.
Answer = bool | list[str]
Ask = Callable[[str], "str | None"]
Show = Callable[[str], None]

CHOICE_ITEMS = (
    "a accept",
    "r reject",
    "e edit",
    "s skip",
    "A accept the rest of the file",
    "R reject the rest of the file",
)
CHOICES = ", ".join(CHOICE_ITEMS)
_BOM = "﻿"


class ReviewStopped(Exception):
    """The input ended at a question: the file asked about is left as it is."""


@dataclass(frozen=True)
class Hunk:
    """One hunk: its number (1-based), its opcode group and the changed spans."""

    n: int
    group: tuple[tuple, ...]
    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass
class FileReview:
    """What ``/review`` did to one file."""

    path: str
    hunks: int = 0
    rejected: int = 0
    edited: int = 0
    rewritten: bool = False
    removed: bool = False
    restored: bool = False
    note: str = ""


@dataclass
class TurnReview:
    """What ``/review`` did to the last turn's files, and what it could not review."""

    turn: str | None
    files: list[FileReview] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stopped: bool = False


def lines(text: str) -> list[str]:
    """The lines of *text* without their ends, counted as ``diff_render`` counts them."""
    if not text:
        return []
    body = text.replace("\r\n", "\n")
    body = body[:-1] if body.endswith("\n") else body
    return body.split("\n")


def hunks(old: str, new: str) -> list[Hunk] | None:
    """The hunks from *old* to *new*; None when the change is too large to split."""
    groups = diff_render.group_hunks(lines(old), lines(new))
    if groups is None:
        return None
    out: list[Hunk] = []
    for group in groups:
        changes = [op for op in group if op[0] != "equal"]
        if not changes:
            continue
        out.append(
            Hunk(
                n=len(out) + 1,
                group=tuple(group),
                old_start=changes[0][1],
                old_end=changes[-1][2],
                new_start=changes[0][3],
                new_end=changes[-1][4],
            )
        )
    return out


def combine(
    old: str,
    new: str,
    found: list[Hunk],
    answers: dict[int, Answer],
    ending: str = "\n",
) -> str:
    """The file built from *new* with each hunk taken as *answers* says.

    A hunk with no answer keeps the turn's text. The text between hunks is the
    same on both sides. Lines are joined with *ending*.
    """
    old_lines, new_lines = lines(old), lines(new)
    out: list[str] = []
    pos = 0
    last_from_new = True
    for hunk in found:
        out += old_lines[pos : hunk.old_start]
        answer = answers.get(hunk.n, True)
        if answer is True:
            out += new_lines[hunk.new_start : hunk.new_end]
        elif answer is False:
            out += old_lines[hunk.old_start : hunk.old_end]
        else:
            out += list(answer)
        pos = hunk.old_end
        if pos == len(old_lines):
            last_from_new = answer is not False
    out += old_lines[pos:]
    if not out:
        return ""
    source = new if last_from_new else old
    return ending.join(out) + (ending if source.endswith("\n") else "")


def _text(data: bytes) -> str | None:
    """UTF-8 text without its byte order mark, or None when the bytes are not UTF-8."""
    try:
        return data.decode("utf-8").removeprefix(_BOM)
    except UnicodeDecodeError:
        return None


def _ask(ask: Ask, question: str) -> str:
    answer = ask(question)
    if answer is None:
        raise ReviewStopped
    return answer.strip()


def _typed_lines(ask: Ask, show: Show) -> list[str]:
    show("Type the new lines for this hunk. End with a line holding only a dot (.).")
    typed: list[str] = []
    while True:
        line = ask("> ")
        if line is None:
            raise ReviewStopped
        if line.strip() == ".":
            return typed
        typed.append(line)


def choice_lines(width: int) -> list[str]:
    """The choices folded at the commas, so no choice is split (J5, B-117)."""
    out: list[str] = []
    current = ""
    for i, item in enumerate(CHOICE_ITEMS):
        piece = item + ("," if i < len(CHOICE_ITEMS) - 1 else "")
        candidate = f"{current} {piece}" if current else piece
        if current and len(candidate) > width:
            out.append(current)
            current = piece
        else:
            current = candidate
    out.append(current)
    return out


def _answer_hunks(
    path: str,
    old: str,
    new: str,
    found: list[Hunk],
    ask: Ask,
    show: Show,
    width: int,
) -> dict[int, Answer]:
    old_lines, new_lines = lines(old), lines(new)
    answers: dict[int, Answer] = {}
    rest: bool | None = None
    for hunk in found:
        if rest is not None:
            answers[hunk.n] = rest
            continue
        show(f"Hunk {hunk.n} of {len(found)} in {safe_text(path)}:")
        for line in diff_render.draw_hunk(
            path, old_lines, new_lines, list(hunk.group), width=width
        ):
            show(line)
        for line in choice_lines(max(width - 3, 20)):
            show(line)
        while True:
            answer = _ask(ask, "answer: ")
            if answer in {"A", "R"}:
                rest = answer == "A"
                answers[hunk.n] = rest
                break
            choice = answer.lower()
            if choice in {"a", "s", "y", "yes", "skip"}:
                answers[hunk.n] = True
                break
            if choice in {"r", "n", "no"}:
                answers[hunk.n] = False
                break
            if choice == "e":
                answers[hunk.n] = _typed_lines(ask, show)
                break
            show("Answer with one of:")
            for line in choice_lines(max(width - 3, 20)):
                show(line)
    return answers


def _whole_file(question: str, ask: Ask) -> bool:
    """True to keep the turn's change to a file that is not split into hunks."""
    while True:
        answer = _ask(ask, f"{question} [k keep, r restore the saved copy]: ").lower()
        if answer in {"k", "a", "keep", "s", "skip", "y"}:
            return True
        if answer in {"r", "n", "restore"}:
            return False


def _write(root: Path, key: str, data: bytes | None) -> None:
    """Write *data* to the workspace file *key*, or remove it when None."""
    target = require_workspace_path(root, key, purpose="write")
    if data is None:
        if target.is_file():
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".ract-review")
    temp.write_bytes(data)
    os.replace(temp, target)


def review_file(
    root: Path,
    turn: str,
    key: str,
    before: bytes | None,
    ask: Ask,
    show: Show,
    width: int = 80,
) -> FileReview:
    """Ask about each hunk the turn made in *key*, and write the answers."""
    result = FileReview(path=key)
    target = root / key
    now = None if target.is_symlink() or not target.is_file() else target.read_bytes()
    if before is None and now is None:
        result.note = f"{safe_text(key)}: the turn created it and it is gone now"
        return result
    if before is not None and now is None:
        # The turn removed the file, or it was removed since.
        show(f"{safe_text(key)}: removed since the turn's copy was saved.")
        if not _whole_file(f"Keep {safe_text(key)} removed?", ask):
            _write(root, key, before)
            result.restored = True
        result.hunks = 1
        return _recorded(root, turn, result)
    assert now is not None
    old_text = "" if before is None else _text(before)
    new_text = _text(now)
    found = None
    if old_text is not None and new_text is not None:
        found = hunks(old_text, new_text)
    if not found:
        # Not UTF-8, too large to split, or only the line ends differ.
        for line in diff_render.render_hunks(
            key,
            None if before is None else (old_text or ""),
            new_text or "",
            width=width,
            max_lines=40,
        ):
            show(line)
        result.hunks = 1
        if not _whole_file(f"Keep the turn's change to {safe_text(key)}?", ask):
            _write(root, key, before)
            result.removed = before is None
            result.restored = before is not None
            result.rejected = 1
        return _recorded(root, turn, result)
    assert old_text is not None and new_text is not None
    answers = _answer_hunks(key, old_text, new_text, found, ask, show, width)
    result.hunks = len(found)
    result.rejected = sum(1 for a in answers.values() if a is False)
    result.edited = sum(1 for a in answers.values() if isinstance(a, list))
    if not result.rejected and not result.edited:
        return result  # every hunk kept: the file stays as the turn left it
    if result.rejected == len(found):
        # Every hunk rejected: the saved bytes come back exactly.
        _write(root, key, before)
        result.removed = before is None
        result.restored = before is not None
        return _recorded(root, turn, result)
    ending = "\r\n" if "\r\n" in new_text else "\n"
    text = combine(old_text, new_text, found, answers, ending)
    bom = _BOM if now.startswith(_BOM.encode("utf-8")) else ""
    _write(root, key, (bom + text).encode("utf-8"))
    result.rewritten = True
    return _recorded(root, turn, result)


def _recorded(root: Path, turn: str, result: FileReview) -> FileReview:
    """Record the file as the review left it, so ``/undo`` still restores it."""
    if result.rewritten or result.removed or result.restored:
        undo_backup.note_reviewed(root, turn, result.path)
    return result


def review_last_turn(
    root: Path | str, ask: Ask, show: Show, width: int = 80
) -> TurnReview:
    """Review each file the last turn changed, hunk by hunk.

    End of input stops the review: the file being asked about is left as it is,
    and files already answered keep their answers.
    """
    base = Path(os.path.realpath(root))
    turns = [
        row
        for row in undo_backup.checkpoints(base)
        if row["kind"] == "turn" and not row["done"]
    ]
    if not turns:
        return TurnReview(turn=None)
    last = turns[0]
    review = TurnReview(turn=last["turn"])
    for key in [*last["saved"], *last["created"]]:
        if undo_backup.check_entry(base, base, key) is not None:
            review.notes.append(
                f"{safe_text(key)} cannot be reviewed: not a project path"
            )
            continue
        before: bytes | None = None
        if key in last["saved"]:
            try:
                before = undo_backup.previous_version(base, last["turn"], key)
            except ValueError:
                before = None
            if before is None:
                review.notes.append(
                    f"{safe_text(key)} cannot be reviewed: the turn's saved copy is missing"
                )
                continue
        try:
            review.files.append(
                review_file(base, last["turn"], key, before, ask, show, width)
            )
        except ReviewStopped:
            review.stopped = True
            break
        except WorkspacePathRefused as refused:
            review.notes.append(f"{safe_text(key)} was not written: {refused}")
    return review


def report_lines(review: TurnReview) -> list[str]:
    """One line per file the review changed, then its notes."""
    out: list[str] = []
    for file in review.files:
        name = safe_text(file.path)
        if file.note:
            out.append(file.note)
        elif file.removed:
            out.append(f"{name}: removed again (the turn created it)")
        elif file.restored:
            out.append(f"{name}: the turn's saved copy is back")
        elif file.rewritten:
            parts = []
            if file.rejected:
                parts.append(f"{file.rejected} of {file.hunks} hunks rejected")
            if file.edited:
                parts.append(f"{file.edited} edited")
            out.append(f"{name}: {', '.join(parts)}")
        else:
            out.append(f"{name}: kept as the turn left it")
    out += review.notes
    if review.stopped:
        out.append("review stopped: the file asked about is left as it is")
    return out
