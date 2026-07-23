# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for SessionStore backup and restore."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.session_store import SessionStore


def test_backup_and_restore_round_trip(tmp_path):
    store_dir = tmp_path / "sessions"
    backup_dir = tmp_path / "backups"
    store = SessionStore(store_dir)
    store.save("sess1", {"intent": "test", "plan": None})

    result = store.backup("sess1", backup_dir)
    assert result["copied"] == ["sess1.json"]
    assert result["missing"] == []
    assert Path(result["backup_dir"]).is_dir()

    # Wipe the original session.
    store._path("sess1").unlink()
    assert not store.exists("sess1")

    restore = store.restore("sess1", result["backup_dir"])
    assert restore["copied"] == ["sess1.json"]
    assert restore["missing"] == []
    assert store.exists("sess1")
    assert store.load("sess1")["intent"] == "test"


def test_backup_missing_session(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    result = store.backup("missing", tmp_path / "backups")
    assert result["copied"] == []
    assert result["missing"] == ["missing.json"]


def test_restore_missing_backup(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    result = store.restore("missing", tmp_path / "backups")
    assert result["copied"] == []
    assert result["missing"] == ["missing.json"]


# RACT 0.1.2 - Trust and tooling
