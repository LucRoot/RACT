"""Tests for :mod:`ract.memory.retrieve` — happy paths against a
seeded symbol + graph index.

Semantic index integration is exercised in
``test_retrieve_cascade.py`` (which gates on lancedb availability).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.events import NullEventSink
from ract.memory.graph_index import EdgeRow, GraphIndex
from ract.memory.retrieve import (
    GraphDir,
    IndexKind,
    IndexRef,
    NestedRetrievalError,
    RetrievalBundle,
    RetrievalQuery,
    RetrievalStrategy,
    SymbolRef,
    canonical_query_payload,
    retrieve,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _seed_symbol(sym: SymbolIndex, tmp_path: Path, *, name: str, body: str) -> int:
    file_path = tmp_path / f"{name}.py"
    file_path.write_text(body, encoding="utf-8")
    row = SymbolRow(
        id=None,
        name=name,
        kind="function",
        file_path=str(file_path),
        start_line=1,
        end_line=body.count("\n") + 1,
        signature=f"def {name}():",
        docstring=None,
        visibility="public",
        parent_symbol_id=None,
        language="python",
        content_hash=f"hash-{name}",
        token_count=len(body.split()),
        updated_at=1,
    )
    return sym.insert_or_update(row)


def _symbol_only_indexes(tmp_path: Path) -> tuple[SymbolIndex, list[IndexRef]]:
    sym = SymbolIndex(str(tmp_path / "sym.db"))
    return sym, [IndexRef(kind=IndexKind.SYMBOL, index=sym)]


def _symbol_and_graph_indexes(
    tmp_path: Path,
) -> tuple[SymbolIndex, GraphIndex, list[IndexRef]]:
    sym = SymbolIndex(str(tmp_path / "sym.db"))
    graph = GraphIndex(str(tmp_path / "graph.db"), symbol_index=sym)
    refs = [
        IndexRef(kind=IndexKind.SYMBOL, index=sym),
        IndexRef(kind=IndexKind.GRAPH, index=graph),
    ]
    return sym, graph, refs


# ---------------------------------------------------------------------------
# Empty-index path
# ---------------------------------------------------------------------------


def test_retrieve_against_empty_index_returns_empty_bundle(tmp_path: Path):
    _, indexes = _symbol_only_indexes(tmp_path)
    query = RetrievalQuery(symbol_names=("Nobody",))
    bundle = retrieve(query, indexes, budget=1000)
    assert isinstance(bundle, RetrievalBundle)
    assert bundle.chunks == ()
    assert bundle.total_tokens == 0
    assert bundle.query_trace.error == "index_not_populated"


def test_retrieve_with_no_seeds_returns_empty(tmp_path: Path):
    _, indexes = _symbol_only_indexes(tmp_path)
    bundle = retrieve(RetrievalQuery(), indexes, budget=1000)
    assert bundle.chunks == ()
    assert bundle.query_trace.error == "index_not_populated"


# ---------------------------------------------------------------------------
# Exact-name path
# ---------------------------------------------------------------------------


def test_retrieve_exact_name_returns_matching_chunk(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    _seed_symbol(sym, tmp_path, name="greet", body="def greet():\n    return 1\n")
    _seed_symbol(sym, tmp_path, name="other", body="def other():\n    return 2\n")

    query = RetrievalQuery(symbol_names=("greet",))
    bundle = retrieve(query, indexes, budget=1000)
    assert len(bundle.chunks) == 1
    assert bundle.chunks[0].symbol_name == "greet"
    assert bundle.total_tokens > 0
    assert bundle.query_trace.final_level == 1
    assert any(hit.operation == "find_by_name" for hit in bundle.query_trace.index_hits)


def test_retrieve_records_call_id_and_source_index(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    _seed_symbol(sym, tmp_path, name="greet", body="def greet():\n    return 1\n")
    bundle = retrieve(RetrievalQuery(symbol_names=("greet",)), indexes, budget=1000)
    assert bundle.call_id
    assert bundle.chunks[0].metadata.get("source_index") == "symbol"


def test_retrieve_emits_events_to_sink(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    _seed_symbol(sym, tmp_path, name="greet", body="def greet():\n    pass\n")
    sink = NullEventSink()
    retrieve(RetrievalQuery(symbol_names=("greet",)), indexes, budget=1000, sink=sink)
    kinds = [kind for kind, _ in sink.records]
    assert "retrieval.requested" in kinds
    assert "retrieval.satisfied" in kinds


# ---------------------------------------------------------------------------
# Keyword path (FTS5)
# ---------------------------------------------------------------------------


def test_retrieve_keyword_hits_via_fts5(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    file_a = tmp_path / "a.py"
    file_a.write_text("def unique_name():\n    return 'greeting'\n", encoding="utf-8")
    row = SymbolRow(
        id=None,
        name="unique_name",
        kind="function",
        file_path=str(file_a),
        start_line=1,
        end_line=2,
        signature="def unique_name():",
        docstring="carries a greeting keyword",
        visibility="public",
        parent_symbol_id=None,
        language="python",
        content_hash="h1",
        token_count=6,
        updated_at=1,
    )
    sym.insert_or_update(row)

    query = RetrievalQuery(keywords=("greeting",))
    bundle = retrieve(query, indexes, budget=1000)
    assert any(chunk.symbol_name == "unique_name" for chunk in bundle.chunks)


# ---------------------------------------------------------------------------
# File-scope + exclude-paths
# ---------------------------------------------------------------------------


def test_file_scope_filters_out_of_scope_matches(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    scope_dir = tmp_path / "in_scope"
    scope_dir.mkdir()
    out_dir = tmp_path / "out_scope"
    out_dir.mkdir()
    in_file = scope_dir / "a.py"
    in_file.write_text("def greet():\n    return 1\n", encoding="utf-8")
    out_file = out_dir / "b.py"
    out_file.write_text("def greet():\n    return 2\n", encoding="utf-8")
    for path in (in_file, out_file):
        sym.insert_or_update(
            SymbolRow(
                id=None,
                name="greet",
                kind="function",
                file_path=str(path),
                start_line=1,
                end_line=2,
                signature="def greet():",
                docstring=None,
                visibility="public",
                parent_symbol_id=None,
                language="python",
                content_hash=f"h-{path.name}",
                token_count=4,
                updated_at=1,
            )
        )

    query = RetrievalQuery(
        symbol_names=("greet",),
        file_scope=(str(scope_dir),),
    )
    bundle = retrieve(query, indexes, budget=1000)
    assert all(str(scope_dir) in chunk.file_path for chunk in bundle.chunks)
    assert len(bundle.chunks) == 1


def test_exclude_paths_blocks_matches(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    file_a = tmp_path / "a.py"
    file_a.write_text("def greet():\n    return 1\n", encoding="utf-8")
    file_b = tmp_path / "b_test.py"
    file_b.write_text("def greet():\n    return 2\n", encoding="utf-8")
    for path in (file_a, file_b):
        sym.insert_or_update(
            SymbolRow(
                id=None,
                name="greet",
                kind="function",
                file_path=str(path),
                start_line=1,
                end_line=2,
                signature="def greet():",
                docstring=None,
                visibility="public",
                parent_symbol_id=None,
                language="python",
                content_hash=f"h-{path.name}",
                token_count=4,
                updated_at=1,
            )
        )

    query = RetrievalQuery(
        symbol_names=("greet",),
        exclude_paths=(str(file_b),),
    )
    bundle = retrieve(query, indexes, budget=1000)
    assert all(chunk.file_path != str(file_b) for chunk in bundle.chunks)


# ---------------------------------------------------------------------------
# Nested retrieve refuses
# ---------------------------------------------------------------------------


def test_depth_over_max_refuses_with_nested_error(tmp_path: Path):
    _, indexes = _symbol_only_indexes(tmp_path)
    with pytest.raises(NestedRetrievalError):
        retrieve(RetrievalQuery(), indexes, budget=100, depth=2)


def test_depth_one_still_permitted(tmp_path: Path):
    _, indexes = _symbol_only_indexes(tmp_path)
    bundle = retrieve(RetrievalQuery(), indexes, budget=100, depth=1)
    assert bundle.query_trace.depth == 1


# ---------------------------------------------------------------------------
# Graph seeds (module_03 integration)
# ---------------------------------------------------------------------------


def test_graph_traversal_ids_include_intermediate_stepping_stones(tmp_path: Path):
    """Second Pass Q2 (PARTIAL) fix: bundle records intermediate ids
    so cache invalidation fires when the stepping-stone symbol
    changes even though its id never landed in a surfaced chunk.
    """
    sym, graph, indexes = _symbol_and_graph_indexes(tmp_path)
    a_id = _seed_symbol(
        sym, tmp_path, name="alpha", body="def alpha():\n    return 1\n"
    )
    b_id = _seed_symbol(sym, tmp_path, name="beta", body="def beta():\n    return 2\n")
    edge = EdgeRow(
        id=None,
        source_symbol_id=a_id,
        target_symbol_id=b_id,
        edge_type="calls",
        location_file=str(tmp_path / "alpha.py"),
        location_line=1,
        strength=1,
        neighborhood_source="lsp",
    )
    graph.insert_edge(edge)

    from ract.memory.retrieve import bundle_symbol_ids

    query = RetrievalQuery(
        graph_seeds=(SymbolRef(symbol_id=a_id),),
        graph_direction=GraphDir.CALLEES,
    )
    bundle = retrieve(query, indexes, budget=1000)
    # The seed id a_id and target b_id both land in traversal_symbol_ids.
    assert a_id in bundle.traversal_symbol_ids
    assert b_id in bundle.traversal_symbol_ids
    # bundle_symbol_ids unions surfaced-chunk ids with traversal ids so
    # invalidate_by_symbol(a_id) drops the bundle even when a_id
    # never appeared as a surfaced chunk (only as a traversal seed).
    assert a_id in bundle_symbol_ids(bundle)
    graph.close()
    sym.close()


def test_graph_seed_returns_neighbours(tmp_path: Path):
    sym, graph, indexes = _symbol_and_graph_indexes(tmp_path)
    a_id = _seed_symbol(
        sym, tmp_path, name="alpha", body="def alpha():\n    return 1\n"
    )
    b_id = _seed_symbol(sym, tmp_path, name="beta", body="def beta():\n    return 2\n")
    # alpha calls beta.
    edge = EdgeRow(
        id=None,
        source_symbol_id=a_id,
        target_symbol_id=b_id,
        edge_type="calls",
        location_file=str(tmp_path / "alpha.py"),
        location_line=1,
        strength=1,
        neighborhood_source="lsp",
    )
    graph.insert_edge(edge)

    query = RetrievalQuery(
        graph_seeds=(SymbolRef(symbol_id=a_id),),
        graph_direction=GraphDir.CALLEES,
    )
    bundle = retrieve(query, indexes, budget=1000)
    names = {chunk.symbol_name for chunk in bundle.chunks}
    assert "beta" in names
    graph.close()
    sym.close()


# ---------------------------------------------------------------------------
# Canonical query payload
# ---------------------------------------------------------------------------


def test_canonical_query_payload_sorts_lists():
    q = RetrievalQuery(symbol_names=("b", "a"), keywords=("y", "x"))
    payload = canonical_query_payload(q)
    assert payload["symbol_names"] == ["a", "b"]
    assert payload["keywords"] == ["x", "y"]
    assert payload["graph_direction"] == "both"


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


def test_core_first_strategy_dedups_by_symbol_id(tmp_path: Path):
    sym, indexes = _symbol_only_indexes(tmp_path)
    # Seed one symbol; keyword hit AND exact-name hit should collapse
    # by symbol id under CORE_FIRST.
    file_a = tmp_path / "a.py"
    file_a.write_text("def greet():\n    return 'hello greet'\n", encoding="utf-8")
    sym.insert_or_update(
        SymbolRow(
            id=None,
            name="greet",
            kind="function",
            file_path=str(file_a),
            start_line=1,
            end_line=2,
            signature="def greet():",
            docstring="hello greet marker",
            visibility="public",
            parent_symbol_id=None,
            language="python",
            content_hash="h1",
            token_count=6,
            updated_at=1,
        )
    )
    query = RetrievalQuery(symbol_names=("greet",), keywords=("greet",))
    bundle = retrieve(
        query, indexes, budget=1000, strategy=RetrievalStrategy.CORE_FIRST
    )
    # Exact + keyword hits collapse to one under CORE_FIRST.
    assert len(bundle.chunks) == 1


def test_content_hash_dedup_collapses_identical_bodies(tmp_path: Path):
    """Two symbols with the same content_hash collapse to one."""
    sym, indexes = _symbol_only_indexes(tmp_path)
    file_a = tmp_path / "a.py"
    file_a.write_text("def greet():\n    return 1\n", encoding="utf-8")
    file_b = tmp_path / "b.py"
    file_b.write_text("def greet():\n    return 1\n", encoding="utf-8")
    for path in (file_a, file_b):
        sym.insert_or_update(
            SymbolRow(
                id=None,
                name="greet",
                kind="function",
                file_path=str(path),
                start_line=1,
                end_line=2,
                signature="def greet():",
                docstring=None,
                visibility="public",
                parent_symbol_id=None,
                language="python",
                content_hash="SHARED_HASH",
                token_count=4,
                updated_at=1,
            )
        )
    query = RetrievalQuery(symbol_names=("greet",))
    bundle = retrieve(query, indexes, budget=1000)
    # Content-hash dedup collapses to one.
    assert len(bundle.chunks) == 1
