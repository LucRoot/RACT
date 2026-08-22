"""TTL enforcement for RetrievalCache (v0.5.1 wiring module_08, Lens E MEM-E-01).

The v0.5.0 cache recorded ``created_at`` but never consulted it, so a
long-lived process could serve indefinitely-old bundles between
watcher invalidations. Module_08 wires TTL enforcement:

- :class:`RetrievalCache` accepts ``ttl_seconds`` (default 3600s).
- :meth:`lookup` returns None + deletes the row when an entry has aged
  past ``created_at + ttl_seconds``.
- :meth:`invalidate_expired` sweeps all expired rows on demand (the
  watcher's periodic scan invokes it each tick).
- ``ttl_seconds <= 0`` disables the check (backward-compat with the
  v0.5.0 unbounded cache).
"""

from __future__ import annotations

import time
from pathlib import Path

from ract.memory.cache import DEFAULT_TTL_SECONDS, RetrievalCache


def _payload_and_bundle() -> tuple[dict[str, object], dict[str, object]]:
    return {"query": "seed"}, {"bundle": True}


def test_default_ttl_is_one_hour(tmp_path: Path) -> None:
    assert DEFAULT_TTL_SECONDS == 3600
    with RetrievalCache(tmp_path / "cache.db") as cache:
        assert cache.ttl_seconds == DEFAULT_TTL_SECONDS


def test_lookup_returns_entry_within_ttl(tmp_path: Path) -> None:
    query, bundle = _payload_and_bundle()
    with RetrievalCache(tmp_path / "cache.db", ttl_seconds=3600) as cache:
        cache.store(query, "commit-hash", bundle, [1], ["a.py"])
        got = cache.lookup(query, "commit-hash")
        assert got == bundle


def test_lookup_expires_entry_past_ttl(tmp_path: Path) -> None:
    """A short-TTL cache must drop the stale row on the next lookup."""
    query, bundle = _payload_and_bundle()
    # ttl_seconds=1 keeps the test deterministic without long sleeps.
    with RetrievalCache(tmp_path / "cache.db", ttl_seconds=1) as cache:
        cache.store(query, "commit-hash", bundle, [1], ["a.py"])
        # Force created_at into the past by rewriting the row.
        with cache._lock:
            cache._conn.execute(
                "UPDATE retrieval_cache SET created_at = ? WHERE repo_commit_hash = ?",
                (int(time.time()) - 3600, "commit-hash"),
            )
        got = cache.lookup(query, "commit-hash")
        assert got is None
        # And the row must be deleted (not just filtered).
        assert cache.count() == 0


def test_ttl_disabled_when_zero(tmp_path: Path) -> None:
    """ttl_seconds=0 preserves the v0.5.0 cache-forever behavior."""
    query, bundle = _payload_and_bundle()
    with RetrievalCache(tmp_path / "cache.db", ttl_seconds=0) as cache:
        cache.store(query, "commit-hash", bundle, [1], ["a.py"])
        with cache._lock:
            cache._conn.execute(
                "UPDATE retrieval_cache SET created_at = ? WHERE repo_commit_hash = ?",
                (0, "commit-hash"),
            )
        assert cache.lookup(query, "commit-hash") == bundle


def test_invalidate_expired_sweeps_all_stale_rows(tmp_path: Path) -> None:
    with RetrievalCache(tmp_path / "cache.db", ttl_seconds=1) as cache:
        cache.store({"q": 1}, "c1", {"b": 1}, [], ["a.py"])
        cache.store({"q": 2}, "c2", {"b": 2}, [], ["b.py"])
        with cache._lock:
            cache._conn.execute(
                "UPDATE retrieval_cache SET created_at = ?",
                (int(time.time()) - 3600,),
            )
        dropped = cache.invalidate_expired()
        assert dropped == 2
        assert cache.count() == 0


def test_invalidate_expired_noop_when_ttl_disabled(tmp_path: Path) -> None:
    with RetrievalCache(tmp_path / "cache.db", ttl_seconds=0) as cache:
        cache.store({"q": 1}, "c1", {"b": 1}, [], ["a.py"])
        assert cache.invalidate_expired() == 0
        assert cache.count() == 1
