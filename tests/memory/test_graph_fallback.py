"""Tests for the symbol-only fallback (module_03 LSP degradation path).

Simulates a missing LSP and asserts the fallback populates
self-referential edges with ``neighborhood_source='symbol_only'``,
emits a WARNING log, and is queryable through the fallback
helpers.
"""

from __future__ import annotations

import logging

from ract.memory.graph_index import GraphIndex
from ract.memory.lsp_fallback import (
    clear_symbol_only_edges,
    has_symbol_only_edges,
    is_symbol_only,
    populate_symbol_only,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _seed(sym: SymbolIndex, count: int, language: str = "python") -> list[int]:
    ids: list[int] = []
    for i in range(count):
        rid = sym.insert_or_update(
            SymbolRow(
                id=None,
                name=f"fn_{i}",
                kind="function",
                file_path=f"module_{language}_{i}.src",
                start_line=1,
                end_line=5,
                signature=f"def fn_{i}(): ...",
                docstring=None,
                visibility="public",
                parent_symbol_id=None,
                language=language,
                content_hash=f"h{i}",
                token_count=3,
                updated_at=None,
            )
        )
        ids.append(rid)
    return ids


def test_fallback_populates_self_referential_edges(caplog):
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        _seed(sym, 3)
        rows = list(_iter_symbols(sym))
        with caplog.at_level(logging.WARNING, logger="ract.memory.lsp_fallback"):
            inserted = populate_symbol_only(
                g, rows, language="python", reason="pylsp not on PATH"
            )
        assert inserted == 3
        assert g.count() == 3
        cur = g.connection.execute(
            "SELECT source_symbol_id, target_symbol_id, neighborhood_source FROM edges"
        )
        for row in cur.fetchall():
            assert row["source_symbol_id"] == row["target_symbol_id"]
            assert row["neighborhood_source"] == "symbol_only"


def test_fallback_logs_warning():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        _seed(sym, 1)
        rows = list(_iter_symbols(sym))
        import logging

        logger = logging.getLogger("ract.memory.lsp_fallback")
        records = []

        class _H(logging.Handler):
            def emit(self, r: logging.LogRecord) -> None:
                records.append(r)

        h = _H(level=logging.WARNING)
        logger.addHandler(h)
        try:
            populate_symbol_only(
                g, rows, language="python", reason="rust-analyzer missing"
            )
        finally:
            logger.removeHandler(h)
        assert any(r.levelno == logging.WARNING for r in records)
        assert any("rust-analyzer missing" in r.getMessage() for r in records)


def test_fallback_scoped_by_language():
    """Fallback only emits edges for symbols matching the language argument."""
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        _seed(sym, 2, language="python")
        _seed(sym, 2, language="rust")
        rows = list(_iter_symbols(sym))
        populate_symbol_only(g, rows, language="python", reason="test")
        # Only two edges (python symbols), not four.
        assert g.count() == 2


def test_is_symbol_only_predicate():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        _seed(sym, 1)
        rows = list(_iter_symbols(sym))
        populate_symbol_only(g, rows, language="python", reason="test")
        # hotspots skips symbol_only edges, so use the raw iterator.
        edges = list(_all_edges(g))
        assert edges
        assert all(is_symbol_only(e) for e in edges)


def test_has_symbol_only_edges_global():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        assert has_symbol_only_edges(g) is False
        _seed(sym, 1)
        populate_symbol_only(g, list(_iter_symbols(sym)), language="python", reason="t")
        assert has_symbol_only_edges(g) is True


def test_has_symbol_only_edges_scoped_by_language():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        _seed(sym, 2, language="python")
        populate_symbol_only(g, list(_iter_symbols(sym)), language="python", reason="t")
        assert has_symbol_only_edges(g, sym, "python") is True
        assert has_symbol_only_edges(g, sym, "rust") is False


def test_clear_symbol_only_edges():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        _seed(sym, 3)
        populate_symbol_only(g, list(_iter_symbols(sym)), language="python", reason="t")
        deleted = clear_symbol_only_edges(g)
        assert deleted == 3
        assert g.count() == 0


def test_fallback_skips_symbols_without_id():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        rows = [
            SymbolRow(
                id=None,
                name="ephemeral",
                kind="function",
                file_path="x.py",
                start_line=1,
                end_line=2,
                signature=None,
                docstring=None,
                visibility=None,
                parent_symbol_id=None,
                language="python",
                content_hash=None,
                token_count=None,
                updated_at=None,
            )
        ]
        inserted = populate_symbol_only(g, rows, language="python", reason="t")
        assert inserted == 0
        assert g.count() == 0


def _iter_symbols(sym: SymbolIndex):
    from ract.memory.symbol_index import _row_from_sqlite

    for row in sym.connection.execute("SELECT * FROM symbols"):
        yield _row_from_sqlite(row)


def _all_edges(g: GraphIndex):
    from ract.memory.graph_index import _row_from_sqlite as edge_from

    for row in g.connection.execute("SELECT * FROM edges"):
        yield edge_from(row)


# RACT 0.5.0
