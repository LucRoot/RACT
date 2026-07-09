# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.session_rollback import SessionRollback, SnapshotNotFoundError


def test_capture_and_restore_roundtrip(tmp_path: Path) -> None:
    rollback = SessionRollback(tmp_path)
    file_path = tmp_path / "src" / "foo.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("original", encoding="utf-8")

    rollback.capture("s1", [file_path])
    file_path.write_text("changed", encoding="utf-8")

    restored, missing = rollback.restore("s1")
    assert file_path.read_text(encoding="utf-8") == "original"
    assert restored == ["src/foo.py"]
    assert missing == []


def test_restore_missing_snapshot_raises(tmp_path: Path) -> None:
    rollback = SessionRollback(tmp_path)
    try:
        rollback.restore("missing")
        assert False, "Expected SnapshotNotFoundError"
    except SnapshotNotFoundError:
        pass


def test_capture_ignores_files_outside_project(tmp_path: Path) -> None:
    rollback = SessionRollback(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    rollback.capture("s1", [outside])
    assert rollback.snapshot_exists("s1") is True

    restored, missing = rollback.restore("s1")
    assert restored == []
    assert missing == []


def test_snapshot_exists(tmp_path: Path) -> None:
    rollback = SessionRollback(tmp_path)
    assert rollback.snapshot_exists("s1") is False
    rollback.capture("s1", [])
    assert rollback.snapshot_exists("s1") is True


def test_list_snapshots(tmp_path: Path) -> None:
    rollback = SessionRollback(tmp_path)
    rollback.capture("a", [])
    rollback.capture("b", [])
    assert sorted(rollback.list_snapshots()) == ["a", "b"]


# RACT 0.1.1 - Trust and Tooling
