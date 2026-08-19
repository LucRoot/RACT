"""Tests for :mod:`ract.memory.cache` — SQLite-backed query cache."""

from __future__ import annotations

from pathlib import Path


from ract.memory.cache import RetrievalCache


def _payload(**over):
    base = {"symbol_names": ["User"], "keywords": [], "graph_seeds": []}
    base.update(over)
    return base


def _bundle_payload():
    return {"chunks": [], "total_tokens": 0}


def test_cache_creates_schema_at_open(tmp_path: Path):
    with RetrievalCache(tmp_path / "retrieval.db") as cache:
        assert cache.count() == 0
        assert cache.store_path.is_file()


def test_lookup_miss_then_hit(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        assert cache.lookup(_payload(), "commit-1") is None
        cache.store(_payload(), "commit-1", _bundle_payload(), [7, 8], ["/repo/f.py"])
        got = cache.lookup(_payload(), "commit-1")
    assert got == _bundle_payload()


def test_different_commit_hash_produces_distinct_key(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(_payload(), "commit-1", {"total_tokens": 1}, [1], ["a"])
        cache.store(_payload(), "commit-2", {"total_tokens": 2}, [1], ["a"])
        assert cache.count() == 2
        assert cache.lookup(_payload(), "commit-1")["total_tokens"] == 1
        assert cache.lookup(_payload(), "commit-2")["total_tokens"] == 2


def test_invalidate_by_symbol_drops_matching_entries(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(_payload(), "c1", _bundle_payload(), [1, 2], ["a"])
        cache.store(_payload(keywords=["x"]), "c1", _bundle_payload(), [3], ["b"])
        # Symbol 2 changed on save.
        deleted = cache.invalidate_by_symbol(2)
        assert deleted == 1
        # Second entry untouched.
        assert cache.count() == 1


def test_invalidate_by_symbol_no_substring_false_positive(tmp_path: Path):
    """id=1 must NOT invalidate a bundle whose symbol_ids contain 12."""
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(_payload(), "c1", _bundle_payload(), [12], ["a"])
        deleted = cache.invalidate_by_symbol(1)
    assert deleted == 0


def test_invalidate_by_symbol_matches_first_and_last_position(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(_payload(), "c1", _bundle_payload(), [7, 2, 12], ["a"])
        cache.store(_payload(keywords=["z"]), "c1", _bundle_payload(), [7], ["b"])
        cache.store(_payload(keywords=["y"]), "c1", _bundle_payload(), [2, 7], ["c"])
        # Symbol 7 appears at first, middle, and last positions.
        assert cache.invalidate_by_symbol(7) == 3


def test_invalidate_by_file_drops_referencing_entries(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(
            _payload(), "c1", _bundle_payload(), [1], ["/repo/a.py", "/repo/b.py"]
        )
        cache.store(
            _payload(keywords=["x"]), "c1", _bundle_payload(), [2], ["/repo/c.py"]
        )
        deleted = cache.invalidate_by_file("/repo/b.py")
        assert deleted == 1
        assert cache.count() == 1


def test_invalidate_all(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(_payload(), "c1", _bundle_payload(), [1], ["a"])
        cache.store(_payload(keywords=["x"]), "c1", _bundle_payload(), [2], ["b"])
        assert cache.invalidate_all() == 2
        assert cache.count() == 0


def test_store_replaces_on_duplicate_key(tmp_path: Path):
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store(_payload(), "c1", {"total_tokens": 1}, [1], ["a"])
        cache.store(_payload(), "c1", {"total_tokens": 42}, [1, 2], ["a", "b"])
        assert cache.count() == 1
        assert cache.lookup(_payload(), "c1")["total_tokens"] == 42


def test_key_stable_across_dict_ordering(tmp_path: Path):
    """canonical_json sorts keys, so equivalent payloads collide."""
    with RetrievalCache(tmp_path / "r.db") as cache:
        cache.store({"a": 1, "b": 2}, "c1", {"n": 1}, [1], ["a"])
        got = cache.lookup({"b": 2, "a": 1}, "c1")
    assert got == {"n": 1}
