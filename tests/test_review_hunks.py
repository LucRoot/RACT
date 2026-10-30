"""B-014c: /review takes, restores or edits the last turn's change hunk by hunk.

Hostile cases first: an escape sequence in a hunk is shown inert, a missing
saved copy is a note (nothing read or written), end of input leaves the file
asked about as it is, and a path from a manifest never leads a write outside
the project. Then the card's cases: reject one hunk of three, reject all,
accept all, edit with a changed line count, a file the turn deleted, a file
the turn created, and /undo staying true after a review.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract import review_hunks, undo_backup
from tests.test_repl import _session
from tests.test_undo import _turn

OLD = "".join(f"line {n}\n" for n in range(1, 31))
# Three hunks, far enough apart that each is drawn on its own.
NEW = (
    OLD.replace("line 2\n", "line two\n")
    .replace("line 15\n", "line fifteen\n")
    .replace("line 28\n", "line twenty-eight\n")
)


def _review(tmp_path: Path, answers: list[str]) -> str:
    session, _, console = _session(answers, config=tmp_path / "ract.yaml")
    session.handle("/review")
    return console.text


def _notes_turn(tmp_path: Path) -> undo_backup.TurnBackup:
    (tmp_path / "notes.txt").write_text(OLD, encoding="utf-8")
    return _turn(tmp_path, {"notes.txt": NEW})


def _read(tmp_path: Path, name: str = "notes.txt") -> str:
    return (tmp_path / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


# --- hostile cases ---------------------------------------------------------


def test_an_escape_sequence_in_a_hunk_is_shown_inert(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text(OLD, encoding="utf-8")
    _turn(tmp_path, {"notes.txt": OLD.replace("line 2\n", "line \x1b[2J\x07two‮\n")})
    text = _review(tmp_path, ["a"])
    assert "\x1b" not in text and "\x07" not in text and "‮" not in text
    assert "Hunk 1 of 1 in notes.txt:" in text


def test_a_missing_saved_copy_is_a_note_and_nothing_is_written(tmp_path: Path) -> None:
    backup = _notes_turn(tmp_path)
    (backup.folder / "notes.txt").unlink()
    text = _review(tmp_path, ["r", "r", "r"])
    assert "notes.txt cannot be reviewed: the turn's saved copy is missing" in text
    assert _read(tmp_path) == NEW


def test_end_of_input_leaves_the_file_as_it_is(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    text = _review(tmp_path, ["r"])  # one answer, then the input ends
    assert "review stopped" in text
    assert _read(tmp_path) == NEW


def test_end_of_input_while_typing_an_edit_leaves_the_file(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    _review(tmp_path, ["e", "half typed"])
    assert _read(tmp_path) == NEW


def test_a_manifest_path_outside_the_project_is_not_reviewed(tmp_path: Path) -> None:
    backup = _notes_turn(tmp_path)
    manifest = backup.folder / undo_backup.MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["saved"].append("../outside.txt")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    text = _review(tmp_path, ["a", "a", "a"])
    assert "../outside.txt cannot be reviewed: not a project path" in text
    assert not (tmp_path.parent / "outside.txt").exists()


def test_note_reviewed_refuses_a_path_the_turn_did_not_change(tmp_path: Path) -> None:
    import pytest

    backup = _notes_turn(tmp_path)
    (tmp_path / "other.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        undo_backup.note_reviewed(tmp_path, backup.turn_id, "other.txt")
    with pytest.raises(ValueError):
        undo_backup.note_reviewed(tmp_path, backup.turn_id, "../notes.txt")
    with pytest.raises(ValueError):
        undo_backup.note_reviewed(tmp_path, "../x", "notes.txt")


# --- the card's cases ------------------------------------------------------


def test_reject_one_hunk_of_three(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    text = _review(tmp_path, ["a", "r", "a"])
    assert _read(tmp_path) == NEW.replace("line fifteen\n", "line 15\n")
    assert "notes.txt: 1 of 3 hunks rejected" in text


def test_reject_all_puts_the_saved_bytes_back(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(OLD.replace("\n", "\r\n").encode("utf-8"))
    _turn(tmp_path, {"notes.txt": NEW})
    before = OLD.replace("\n", "\r\n").encode("utf-8")
    text = _review(tmp_path, ["R"])
    assert (tmp_path / "notes.txt").read_bytes() == before
    assert "notes.txt: the turn's saved copy is back" in text


def test_accept_all_leaves_the_file_untouched(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    written = (tmp_path / "notes.txt").read_bytes()
    text = _review(tmp_path, ["a", "s", "A"])
    assert (tmp_path / "notes.txt").read_bytes() == written
    assert "notes.txt: kept as the turn left it" in text


def test_edit_a_hunk_with_a_changed_line_count(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    text = _review(tmp_path, ["e", "line 2a", "line 2b", "line 2c", ".", "a", "a"])
    assert _read(tmp_path) == NEW.replace("line two\n", "line 2a\nline 2b\nline 2c\n")
    assert "notes.txt: 1 edited" in text


def test_a_rewritten_file_keeps_its_line_ends(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text(OLD, encoding="utf-8")
    backup = _turn(tmp_path, {"notes.txt": NEW})
    # The turn's file has CRLF ends (text mode on Windows writes them).
    (tmp_path / "notes.txt").write_bytes(NEW.replace("\n", "\r\n").encode("utf-8"))
    undo_backup.note_reviewed(tmp_path, backup.turn_id, "notes.txt")
    _review(tmp_path, ["r", "a", "a"])
    data = (tmp_path / "notes.txt").read_bytes()
    assert b"line 2\r\n" in data and b"line fifteen\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_a_file_the_turn_deleted_can_be_restored(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text("gone soon\n", encoding="utf-8")
    _turn(tmp_path, {"old.md": None})
    text = _review(tmp_path, ["r"])
    assert _read(tmp_path, "old.md") == "gone soon\n"
    assert "old.md: the turn's saved copy is back" in text


def test_a_file_the_turn_deleted_stays_deleted_when_kept(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text("gone soon\n", encoding="utf-8")
    _turn(tmp_path, {"old.md": None})
    _review(tmp_path, ["k"])
    assert not (tmp_path / "old.md").exists()


def test_a_file_the_turn_created_is_removed_when_rejected(tmp_path: Path) -> None:
    _turn(tmp_path, {"notes.py": 'NOTE = "two"\n'})
    text = _review(tmp_path, ["r"])
    assert not (tmp_path / "notes.py").exists()
    assert "notes.py: removed again (the turn created it)" in text


def test_undo_stays_true_after_a_review(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    _review(tmp_path, ["a", "r", "a"])
    result = undo_backup.undo(tmp_path)
    assert result.restored == ["notes.txt"] and not result.skipped
    assert _read(tmp_path) == OLD


def test_diff_shows_the_file_as_the_review_left_it(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    _review(tmp_path, ["r", "a", "a"])
    session, _, console = _session([], config=tmp_path / "ract.yaml")
    session.handle("/diff")
    assert "line two" not in console.text and "line fifteen" in console.text


def test_no_turn_yet(tmp_path: Path) -> None:
    assert "no turn has changed a file yet" in _review(tmp_path, [])


def test_an_unknown_answer_asks_again(tmp_path: Path) -> None:
    _notes_turn(tmp_path)
    text = _review(tmp_path, ["maybe", "A"])
    assert "Answer with one of" in text
    assert _read(tmp_path) == NEW


def test_the_question_fits_40_columns(tmp_path: Path, monkeypatch) -> None:
    import shutil
    import os

    monkeypatch.setattr(
        shutil, "get_terminal_size", lambda *a, **k: os.terminal_size((40, 24))
    )
    _notes_turn(tmp_path)
    text = _review(tmp_path, ["A"])
    for line in text.splitlines():
        assert len(line) <= 40, line


def test_help_lists_review(tmp_path: Path) -> None:
    session, _, console = _session([], config=tmp_path / "ract.yaml")
    session.handle("/help")
    assert "/review" in console.text


def test_the_hunks_are_the_ones_the_summary_draws() -> None:
    from ract import diff_render

    found = review_hunks.hunks(OLD, NEW)
    drawn = [
        line
        for line in diff_render.render_hunks("notes.txt", OLD, NEW)
        if line.startswith("notes.txt: lines")
    ]
    assert [h.n for h in found] == [1, 2, 3] and len(drawn) == 3
    assert review_hunks.combine(OLD, NEW, found, {}) == NEW
    assert review_hunks.combine(OLD, NEW, found, {1: False, 2: False, 3: False}) == OLD
