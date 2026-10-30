"""B-049: `/undo` and `ract undo` reverse the last turn from its backup.

The turn summary named the folder holding the previous versions and gave
the user no command to use it. This interim, file-level undo is built on
the S-026 backups; checkpoints (B-013, gated) will supersede it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ract import undo_backup
from tests.test_headless import _ract
from tests.test_session_turn import _repo


def _turn(root: Path, writes: dict[str, str | None]) -> undo_backup.TurnBackup:
    """A turn that writes (or, for None, deletes) files through the backup."""
    with undo_backup.turn(root) as backup:
        for rel, text in writes.items():
            undo_backup.save_before_replace(root, [rel])
            path = root / rel
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    return backup


def test_a_real_fix_turn_is_undone_byte_for_byte(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    run = _ract(ws, "run", "--config", "ract.yaml", "--yolo", "--", "fix add")
    assert run.returncode == 0, run.stdout + run.stderr
    assert (ws / "src" / "calc.py").read_bytes() != before

    result = _ract(ws, "undo", "--config", "ract.yaml")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (ws / "src" / "calc.py").read_bytes() == before
    assert "restored src/calc.py" in result.stdout


def test_created_files_are_removed_and_deleted_ones_return(tmp_path: Path) -> None:
    # Works outside a git repository: tmp_path is not one.
    (tmp_path / "old.txt").write_text("keep me\n", encoding="utf-8")
    _turn(tmp_path, {"new.txt": "made by the turn\n", "old.txt": None})

    result = undo_backup.undo(tmp_path)

    assert result.removed == ["new.txt"] and result.restored == ["old.txt"]
    assert not (tmp_path / "new.txt").exists()
    assert (tmp_path / "old.txt").read_text(encoding="utf-8") == "keep me\n"


def test_a_file_edited_after_the_turn_is_skipped_unless_forced(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("original\n", encoding="utf-8")
    _turn(tmp_path, {"a.txt": "by RACT\n"})
    (tmp_path / "a.txt").write_text("my own edit after the turn\n", encoding="utf-8")

    result = undo_backup.undo(tmp_path)

    assert result.skipped == ["a.txt"]
    assert (tmp_path / "a.txt").read_text(
        encoding="utf-8"
    ) == "my own edit after the turn\n"
    assert any("/undo --force overwrites it" in line for line in result.lines("undo"))
    # A skipped undo stays pending; --force then restores.
    forced = undo_backup.undo(tmp_path, force=True)
    assert forced.restored == ["a.txt"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "original\n"


def test_nothing_left_to_undo_says_so(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _turn(tmp_path, {"a.txt": "two\n"})

    assert undo_backup.undo(tmp_path).restored == ["a.txt"]
    second = undo_backup.undo(tmp_path)

    assert second.folder is None
    assert second.lines("undo") == [
        "nothing to undo: no turn RACT can reverse is recorded here"
    ]


def test_redo_reverses_the_last_undo_once(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _turn(tmp_path, {"a.txt": "two\n", "b.txt": "new\n"})
    undo_backup.undo(tmp_path)
    assert not (tmp_path / "b.txt").exists()

    again = undo_backup.redo(tmp_path)

    assert sorted(again.restored) == ["a.txt", "b.txt"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "new\n"
    assert undo_backup.redo(tmp_path).folder is None  # only once


def test_the_manifest_records_what_ract_left(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    backup = _turn(tmp_path, {"a.txt": "two\n", "c.txt": "three\n"})

    manifest = json.loads((backup.folder / "manifest.json").read_text("utf-8"))

    assert manifest["kind"] == "turn" and manifest["done"] is False
    assert manifest["saved"] == ["a.txt"] and manifest["created"] == ["c.txt"]
    assert set(manifest["after"]) == {"a.txt", "c.txt"}


def test_the_session_command(tmp_path: Path) -> None:
    from tests.test_repl import _session

    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _turn(tmp_path, {"a.txt": "two\n"})
    session, _, console = _session(config=tmp_path / "ract.yaml")

    session.handle("/undo")

    assert "restored a.txt" in console.text
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\n"
