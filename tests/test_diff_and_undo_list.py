"""B-085: /diff and /undo list (UX standards 13 and 4).

``/diff`` draws the last turn's changes from the copies the turn saved;
``/undo list`` shows each checkpoint with its time, its files and its turn.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ract import undo_backup
from tests.test_repl import _session
from tests.test_undo import _turn


def _shown(tmp_path: Path, command: str) -> str:
    session, _, console = _session(config=tmp_path / "ract.yaml")
    session.handle(command)
    return console.text


def test_diff_shows_a_changed_a_new_and_a_deleted_file(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", "utf-8")
    (tmp_path / "old.md").write_text("gone soon\n", encoding="utf-8")
    _turn(
        tmp_path,
        {
            "calc.py": "def add(a, b):\n    return a + b\n",
            "notes.py": 'NOTE = "two"\n',
            "old.md": None,
        },
    )
    text = _shown(tmp_path, "/diff")
    assert "return a - b" in text and "return a + b" in text
    assert "notes.py" in text and 'NOTE = "two"' in text
    assert "old.md" in text and "gone soon" in text


def test_a_backup_removed_by_hand_says_so(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("x = 1\n", encoding="utf-8")
    backup = _turn(tmp_path, {"calc.py": "x = 2\n"})
    (backup.folder / "calc.py").unlink()
    text = _shown(tmp_path, "/diff")
    assert "diff not available for calc.py" in text


def test_no_turn_yet(tmp_path: Path) -> None:
    assert "no turn has changed a file yet" in _shown(tmp_path, "/diff")
    assert "no checkpoints yet" in _shown(tmp_path, "/undo list")


def test_undo_list_names_each_checkpoint(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    first = _turn(tmp_path, {"a.txt": "two\n"})
    second = _turn(tmp_path, {"b.txt": "new\n"})
    text = _shown(tmp_path, "/undo list")
    assert second.turn_id in text and first.turn_id in text
    assert text.index(second.turn_id) < text.index(first.turn_id)  # newest first
    assert "1 file: b.txt" in text and "1 file: a.txt" in text
    rows = undo_backup.checkpoints(tmp_path)
    assert rows[0]["time"] and rows[0]["kind"] == "turn"


def test_a_file_name_with_escape_sequences_is_shown_escaped(tmp_path: Path) -> None:
    name = "a\x1b[31m.txt"
    try:
        (tmp_path / name).write_text("one\n", encoding="utf-8")
    except OSError:
        name = "a\x07b.txt"  # a file system that refuses ESC still takes BEL? try it
        try:
            (tmp_path / name).write_text("one\n", encoding="utf-8")
        except OSError:
            import pytest

            pytest.skip("this file system refuses control characters in names")
    _turn(tmp_path, {name: "two\n"})
    for command in ("/diff", "/undo list"):
        text = _shown(tmp_path, command)
        assert "\x1b" not in text and "\x07" not in text


def test_both_fit_40_columns(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "calc.py").write_text("x = 1\n", encoding="utf-8")
    _turn(
        tmp_path, {"calc.py": "x = 2\n", "src/a/very/long/path/name/module.py": "y\n"}
    )
    monkeypatch.setattr(
        shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): __import__("os").terminal_size((40, 24)),
    )
    for command in ("/diff", "/undo list"):
        lines = _shown(tmp_path, command).splitlines()
        assert lines and all(len(line) <= 40 for line in lines), (command, lines)
