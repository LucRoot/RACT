"""Symbol-only fallback for the module_03 graph populator.

When the LSP for a language is missing (not installed, wrong
version, crashed), the graph populator downgrades to symbol-only
mode: instead of edges derived from LSP references, one self-
referential edge is inserted per symbol, marked with
``neighborhood_source='symbol_only'``.

Downstream retrieval (module_05) treats a ``symbol_only`` edge as
"no neighborhood" rather than "the symbol calls itself"; the
``research`` output for the language carries a
``neighborhood_source: 'symbol_only'`` marker so the model is not
misled (Second Pass Q2). This module encodes the shape of that
degradation without importing from module_05 (which does not
exist yet); the marker is on the edge row and any downstream
consumer reads it there.

Also emits a structured log record through the RACT logging
surface so a caller looking at the trace can spot the
degradation without reading the graph store.
"""

from __future__ import annotations

import logging
from typing import Iterable

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.graph_index import EdgeRow, GraphIndex
from ract.memory.symbol_index import SymbolIndex, SymbolRow


_LOGGER = logging.getLogger(__name__)


def populate_symbol_only(
    graph: GraphIndex,
    symbols: Iterable[SymbolRow],
    language: str,
    reason: str,
) -> int:
    """Insert one self-referential edge per symbol under ``language``.

    Returns the number of edges inserted. Emits one WARNING log
    record naming ``language`` and ``reason`` so the degradation
    is visible in the operator's log stream.

    Skips symbols whose ``id`` is ``None`` (never persisted) or
    whose ``language`` does not match ``language`` (fallback is
    scoped per language; a mixed-language batch would risk
    inserting edges for languages where the LSP was available).
    """
    edges: list[EdgeRow] = []
    for symbol in symbols:
        if symbol.id is None:
            continue
        if symbol.language != language:
            continue
        edges.append(
            EdgeRow(
                id=None,
                source_symbol_id=symbol.id,
                target_symbol_id=symbol.id,
                edge_type="references",
                location_file=symbol.file_path,
                location_line=symbol.start_line,
                strength=1,
                neighborhood_source="symbol_only",
            )
        )
    if edges:
        graph.insert_edges(edges)
    _LOGGER.warning(
        "graph_index fallback: language=%s reason=%s edges_inserted=%d "
        "(downstream retrieval MUST read neighborhood_source before "
        "rendering a neighborhood claim)",
        language,
        reason,
        len(edges),
    )
    return len(edges)


def is_symbol_only(edge: EdgeRow) -> bool:
    """Return True iff ``edge`` was populated by the fallback path.

    Convenience helper for downstream retrieval so a consumer does
    not have to remember the exact string label.
    """
    return edge.neighborhood_source == "symbol_only"


def has_symbol_only_edges(
    graph: GraphIndex,
    symbol_index: SymbolIndex | None = None,
    language: str | None = None,
) -> bool:
    """Return True iff ``graph`` contains any fallback edges.

    Diagnostic for the operator's "did the LSP go down" question.
    ``language=None`` reports across all languages; passing a
    language requires ``symbol_index`` so the query can filter
    edge source ids against symbol rows for that language.
    """
    if language is None or symbol_index is None:
        cur = graph.connection.execute(
            "SELECT 1 FROM edges WHERE neighborhood_source = 'symbol_only' LIMIT 1"
        )
        return cur.fetchone() is not None
    # Two separate SQLite stores; take a two-step approach.
    src_ids = graph.connection.execute(
        "SELECT DISTINCT source_symbol_id FROM edges "
        "WHERE neighborhood_source = 'symbol_only'"
    ).fetchall()
    if not src_ids:
        return False
    ids = [row["source_symbol_id"] for row in src_ids]
    placeholders = ",".join("?" * len(ids))
    row = symbol_index.connection.execute(
        f"SELECT 1 FROM symbols WHERE id IN ({placeholders}) AND language = ? LIMIT 1",
        tuple(ids) + (language,),
    ).fetchone()
    return row is not None


def clear_symbol_only_edges(
    graph: GraphIndex, symbol_index: SymbolIndex | None = None
) -> int:
    """Delete every fallback edge in ``graph``.

    Called when the LSP comes back online (a live re-run of the
    populator overwrites the fallback). Returns the number of
    edges deleted. ``symbol_index`` is currently unused but is
    kept in the signature so a future scoped-by-language delete
    (module_04+) does not break callers.
    """
    del symbol_index  # reserved for language-scoped delete
    cur = graph.connection.execute(
        "DELETE FROM edges WHERE neighborhood_source = 'symbol_only'"
    )
    graph.connection.commit()
    return cur.rowcount


__all__ = [
    "clear_symbol_only_edges",
    "has_symbol_only_edges",
    "is_symbol_only",
    "populate_symbol_only",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
