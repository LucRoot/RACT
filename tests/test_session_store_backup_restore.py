"""Tests for SessionStore backup and restore."""

from __future__ import annotations


from pathlib import Path

from ract.session_store import SessionStore


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


def test_restore_replaces_a_planted_link(tmp_path):
    from tests.test_b224_atomic_sites import _plant

    store = SessionStore(tmp_path / "sessions")
    store.save("sess1", {"intent": "original"})
    backup = store.backup("sess1", tmp_path / "backups")
    backup_dir = Path(backup["backup_dir"])

    target = store._path("sess1")
    target.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    _plant(target, outside)

    result = store.restore("sess1", backup_dir)

    assert result["copied"] == ["sess1.json"]
    assert outside.read_text(encoding="utf-8") == "sentinel\n"
    assert not target.is_symlink()
    assert store.load("sess1") == {"intent": "original"}


def test_restore_failure_mid_copy_keeps_live_file(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    store.save("sess1", {"intent": "original"})
    backup = store.backup("sess1", tmp_path / "backups")
    backup_dir = Path(backup["backup_dir"])

    def boom(src, dst, *args, **kwargs):
        raise OSError("simulated crash between write and rename")

    monkeypatch.setattr("ract.session_store.shutil.copy2", boom, raising=False)
    try:
        store.restore("sess1", backup_dir)
        assert False, "Expected the simulated crash to propagate"
    except OSError:
        pass
    assert store.load("sess1") == {"intent": "original"}
    assert list((tmp_path / "sessions").glob("*.ract-tmp")) == []
