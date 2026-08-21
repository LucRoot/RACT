"""Memory indexes share the watcher (v0.5.1 wiring module_08 grep-gate).

The Lens E MEM-E-02 finding was that :class:`SymbolIndexWatcher` only
updated :class:`SymbolIndex` and the other three indexes (graph,
graph_populator, semantic) drifted silently. Module_08 extends the
watcher to accept + cascade to each index. This grep-gate keeps
regression pressure on that closure:

- Every memory-side index update helper (``update_file`` on the graph
  populator, ``update_symbol`` on the semantic builder, and
  ``invalidate_by_file`` on the retrieval cache) must be exercised by
  :mod:`ract.memory.watcher`. A future refactor that renames the
  cascade sites or splits the watcher into per-index watchers
  without updating this gate trips the assertion here.
"""

from __future__ import annotations

from pathlib import Path


def _watcher_source() -> str:
    root = Path(__file__).resolve().parents[2]
    text = (root / "src" / "ract" / "memory" / "watcher.py").read_text(
        encoding="utf-8"
    )
    assert text, "watcher.py should not be empty"
    return text


def test_watcher_accepts_cache_handle() -> None:
    src = _watcher_source()
    assert "cache: Any | None = None" in src, (
        "SymbolIndexWatcher must accept an optional RetrievalCache handle"
    )


def test_watcher_accepts_graph_populator_handle() -> None:
    src = _watcher_source()
    assert "graph_populator: Any | None = None" in src, (
        "SymbolIndexWatcher must accept an optional GraphPopulator handle"
    )


def test_watcher_accepts_semantic_index_handle() -> None:
    src = _watcher_source()
    assert "semantic_index: Any | None = None" in src, (
        "SymbolIndexWatcher must accept an optional SemanticIndex handle"
    )


def test_watcher_invokes_graph_populator_update_file() -> None:
    src = _watcher_source()
    assert "self.graph_populator.update_file" in src, (
        "Cascade must invoke GraphPopulator.update_file on source change"
    )


def test_watcher_invokes_semantic_update_symbol() -> None:
    src = _watcher_source()
    # The import may be under an alias; assert both the import and the
    # call site.
    assert "from ract.memory.semantic_builder import" in src
    assert "_semantic_update_symbol" in src, (
        "Cascade must invoke semantic_builder.update_symbol per fresh symbol"
    )


def test_watcher_invokes_cache_invalidate_by_file() -> None:
    src = _watcher_source()
    assert "self.cache.invalidate_by_file" in src, (
        "Cascade must invalidate the RetrievalCache by file on source change"
    )


def test_watcher_periodic_scan_invokes_ttl_sweep() -> None:
    src = _watcher_source()
    assert "self.cache.invalidate_expired" in src, (
        "Periodic scan must exercise cache TTL enforcement"
    )


def test_watcher_emits_memory_freshness_gap_event() -> None:
    src = _watcher_source()
    assert '"memory.freshness_gap"' in src, (
        "Watcher cascade must emit memory.freshness_gap for operator visibility"
    )
