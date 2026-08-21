"""Cache invalidation on watcher-driven source change.

v0.5.1 wiring module_08 (Lens E MEM-E-01) closure. The watcher now
holds an optional :class:`RetrievalCache` handle and calls
:meth:`RetrievalCache.invalidate_by_file` in the cascade after each
reindex. A cached bundle whose ``file_paths_csv`` names the changed
path drops out of the cache on the same flush that reindexes it.
"""

from __future__ import annotations

import time
from pathlib import Path

from ract.memory.cache import RetrievalCache
from ract.memory.symbol_index import SymbolIndex
from ract.memory.watcher import SymbolIndexWatcher


def _wait_for(predicate, *, timeout=3.0, tick=0.05, watcher=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if watcher is not None:
            watcher.flush()
        if predicate():
            return True
        time.sleep(tick)
    if watcher is not None:
        watcher.flush()
    return predicate()


def test_watcher_invalidates_cache_entry_touching_modified_file(
    tmp_path: Path,
) -> None:
    """A cache entry whose file_paths_csv names the changed file drops."""
    source = tmp_path / "target.py"
    source.write_text("def a(): return 1\n", encoding="utf-8")

    with RetrievalCache(tmp_path / "cache.db") as cache, SymbolIndex() as idx:
        # Seed the cache with a bundle keyed on the source file.
        cache.store(
            {"query": "seed"},
            "commit-x",
            {"bundle": "payload"},
            [1],
            [str(source)],
        )
        assert cache.count() == 1

        watcher = SymbolIndexWatcher(
            tmp_path,
            idx,
            cache=cache,
            debounce_seconds=0.05,
        )
        with watcher:
            # Modify the file -> watcher fires _reindex_write ->
            # cascade invalidates the cache row.
            source.write_text("def a(): return 2\n", encoding="utf-8")
            assert _wait_for(
                lambda: cache.count() == 0,
                watcher=watcher,
            ), f"expected cache emptied; still has {cache.count()} rows"
        assert watcher.stats.cache_invalidations >= 1
