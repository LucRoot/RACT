"""Watcher cascade fires on all attached memory indexes.

v0.5.1 wiring module_08 (Lens E MEM-E-02) closure. The v0.5.0
:class:`SymbolIndexWatcher` only updated :class:`SymbolIndex`; the
graph, graph_populator, and semantic indexes drifted silently after
the first save. Module_08 extends the watcher to hold optional
graph_populator + semantic_index + cache handles and cascade the
update to each on every reindex.

These tests use light stub objects for graph_populator + semantic_index
so the cascade wiring can be verified without standing up a real LSP
client or LanceDB store. Real-index integration is covered by the
per-index tests in ``tests/memory/``.
"""

from __future__ import annotations

import time
from pathlib import Path

from ract.memory.cache import RetrievalCache
from ract.memory.symbol_index import SymbolIndex
from ract.memory.watcher import SymbolIndexWatcher


class _FakeGraphPopulator:
    """Minimal stub matching the shape ``_cascade_write`` invokes."""

    def __init__(self) -> None:
        self.update_calls: list[Path] = []
        self.delete_calls: list[str] = []
        self._graph = self  # so _cascade_delete finds .delete_by_source_file

    def update_file(self, path: Path) -> object:
        self.update_calls.append(Path(path))

        class _Report:
            deleted = 0
            inserted = 1
            elapsed_ms = 0

        return _Report()

    def delete_by_source_file(self, path_str: str) -> int:
        self.delete_calls.append(path_str)
        return 1


class _FakeSemanticIndex:
    def __init__(self) -> None:
        self.deleted_files: list[str] = []
        self.per_symbol_updates: list[int] = []

    def delete_by_file(self, path_str: str) -> int:
        self.deleted_files.append(path_str)
        return 0


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


def test_watcher_cascades_write_to_graph_and_cache(tmp_path: Path) -> None:
    source = tmp_path / "x.py"
    source.write_text("def a(): return 1\n", encoding="utf-8")
    graph = _FakeGraphPopulator()
    with RetrievalCache(tmp_path / "cache.db") as cache, SymbolIndex() as idx:
        cache.store({"q": "seed"}, "c1", {"b": 1}, [1], [str(source)])
        watcher = SymbolIndexWatcher(
            tmp_path,
            idx,
            cache=cache,
            graph_populator=graph,
            debounce_seconds=0.05,
        )
        with watcher:
            # Mutate the file so the watcher fires _reindex_write.
            source.write_text("def a(): return 2\n", encoding="utf-8")
            assert _wait_for(
                lambda: (
                    len(graph.update_calls) >= 1
                    and watcher.stats.cache_invalidations >= 1
                ),
                watcher=watcher,
            ), f"cascade stats: {watcher.stats!r}"
        # Graph got the fresh file.
        assert Path(source) in [Path(p) for p in graph.update_calls]
        # Cache row keyed on the file has been evicted.
        assert cache.count() == 0


def test_watcher_cascades_delete_to_graph_semantic_and_cache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "y.py"
    source.write_text("def b(): return 1\n", encoding="utf-8")
    graph = _FakeGraphPopulator()
    semantic = _FakeSemanticIndex()
    with RetrievalCache(tmp_path / "cache.db") as cache, SymbolIndex() as idx:
        cache.store({"q": "seed"}, "c1", {"b": 1}, [1], [str(source)])
        watcher = SymbolIndexWatcher(
            tmp_path,
            idx,
            cache=cache,
            graph_populator=graph,
            semantic_index=semantic,
            debounce_seconds=0.05,
        )
        with watcher:
            source.unlink()
            assert _wait_for(
                lambda: (
                    len(graph.delete_calls) >= 1
                    and len(semantic.deleted_files) >= 1
                    and watcher.stats.cache_invalidations >= 1
                ),
                watcher=watcher,
            ), f"cascade stats: {watcher.stats!r}"
        assert str(source) in graph.delete_calls
        assert str(source) in semantic.deleted_files
        assert cache.count() == 0


def test_periodic_scan_invokes_cache_ttl_sweep(tmp_path: Path) -> None:
    """Watcher's periodic scan invokes RetrievalCache.invalidate_expired."""
    with (
        RetrievalCache(tmp_path / "cache.db", ttl_seconds=1) as cache,
        SymbolIndex() as idx,
    ):
        cache.store({"q": 1}, "c1", {"b": 1}, [], ["a.py"])
        # Force stale created_at so the sweep drops the row.
        with cache._lock:
            cache._conn.execute(
                "UPDATE retrieval_cache SET created_at = ?",
                (int(time.time()) - 3600,),
            )
        watcher = SymbolIndexWatcher(
            tmp_path,
            idx,
            cache=cache,
            debounce_seconds=0.05,
            periodic_scan_seconds=60.0,
        )
        # Call run_periodic_scan directly; the sweep runs even with a
        # long scan interval so we do not have to wait for the thread.
        watcher.run_periodic_scan()
        assert cache.count() == 0
        assert watcher.stats.ttl_evictions >= 1


def test_watcher_backward_compat_without_cascade_handles(tmp_path: Path) -> None:
    """Existing callers passing only (root, index) still work."""
    source = tmp_path / "z.py"
    source.write_text("def c(): return 1\n", encoding="utf-8")
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.05)
        with watcher:
            source.write_text("def c(): return 2\n", encoding="utf-8")
            assert _wait_for(
                lambda: any(r.name == "c" for r in idx.find_in_file(str(source))),
                watcher=watcher,
            )
