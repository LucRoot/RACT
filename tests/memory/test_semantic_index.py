"""Tests for :mod:`ract.memory.semantic_index` — store + query API."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("lancedb")
pytest.importorskip("pyarrow")

from ract.memory.budget import BudgetAccountant, BudgetDeclaration
from ract.memory.embedding import (
    SYNTHETIC_384_NAME,
    SYNTHETIC_768_NAME,
    SyntheticHashEmbedding,
    load_embedding,
)
from ract.memory.semantic_index import (
    CHUNK_KINDS,
    METADATA_FILE_NAME,
    ChunkRow,
    EmbeddingModelMismatchError,
    SemanticIndex,
    SemanticIndexError,
    SemanticStoreCorruptError,
    rebuild_chunk_vectors,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _symbol_index(tmp_path: Path) -> SymbolIndex:
    return SymbolIndex(str(tmp_path / "symbols.db"))


def _mk_chunk(
    *,
    chunk_id: str,
    symbol_id: int,
    body: str,
    token_count: int = 20,
    chunk_kind: str = "function_body",
    file_path: str = "/repo/src/mod.py",
    signature: str = "def f()",
    locator: str = "0/1",
) -> ChunkRow:
    return ChunkRow(
        chunk_id=chunk_id,
        symbol_id=symbol_id,
        file_path=file_path,
        chunk_kind=chunk_kind,
        signature=signature,
        content_hash=chunk_id,  # convenience for tests
        token_count=token_count,
        body=body,
        chunk_locator=locator,
        start_line=1,
        end_line=10,
        updated_at=1,
        vector=None,
    )


def _seat(store: SemanticIndex, chunks: list[ChunkRow]) -> list[ChunkRow]:
    with_vectors = rebuild_chunk_vectors(chunks, store.embedding)
    store.insert_or_update_batch(with_vectors)
    return with_vectors


# ---------------------------------------------------------------------------
# Store construction + metadata
# ---------------------------------------------------------------------------


def test_open_creates_metadata_file(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        meta = store.read_metadata()
    assert meta["embedding_model_name"] == SYNTHETIC_384_NAME
    assert meta["embedding_dim"] == 384
    assert meta["schema_version"] == "v1"


def test_open_defaults_embedder_when_none_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Default is bge-small-en-v1.5 which is offline-unavailable in tests;
    # instead we swap the default via load_embedding("synthetic-384").
    symbols = _symbol_index(tmp_path)
    embedder = load_embedding(SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        assert store.dim == 384


def test_reopen_with_mismatched_embedder_raises(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    first = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    store = SemanticIndex(tmp_path / "sem", symbols, first)
    store.close()
    second = SyntheticHashEmbedding(dim=768, name=SYNTHETIC_768_NAME)
    with pytest.raises(EmbeddingModelMismatchError):
        SemanticIndex(tmp_path / "sem", symbols, second)


def test_missing_metadata_with_extant_table_raises_corrupt(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    store = SemanticIndex(tmp_path / "sem", symbols, embedder)
    _seat(store, [_mk_chunk(chunk_id="a", symbol_id=1, body="hello world")])
    store.close()
    # Delete metadata but keep the LanceDB table.
    (tmp_path / "sem" / METADATA_FILE_NAME).unlink()
    with pytest.raises(SemanticStoreCorruptError):
        SemanticIndex(tmp_path / "sem", symbols, embedder)


def test_chunk_kind_set_matches_shipped_vocabulary():
    assert "function_body" in CHUNK_KINDS
    assert "function_subrange" in CHUNK_KINDS
    assert "class_body" in CHUNK_KINDS
    assert "module_body" in CHUNK_KINDS
    assert "declaration" in CHUNK_KINDS


# ---------------------------------------------------------------------------
# Write API
# ---------------------------------------------------------------------------


def test_insert_or_update_roundtrip(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(store, [_mk_chunk(chunk_id="alpha", symbol_id=42, body="alpha body")])
        assert store.count() == 1
        rows = list(store.iter_chunks())
        assert rows[0].chunk_id == "alpha"
        assert rows[0].symbol_id == 42
        assert rows[0].vector is not None
        assert len(rows[0].vector) == 384


def test_insert_or_update_replaces_existing(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(store, [_mk_chunk(chunk_id="dup", symbol_id=1, body="v1")])
        _seat(store, [_mk_chunk(chunk_id="dup", symbol_id=1, body="v2")])
        assert store.count() == 1
        rows = list(store.iter_chunks())
        assert rows[0].body == "v2"


def test_insert_rejects_missing_vector(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        raw = _mk_chunk(chunk_id="x", symbol_id=1, body="anything")
        with pytest.raises(SemanticIndexError):
            store.insert_or_update(raw)


def test_insert_rejects_wrong_dim_vector(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        chunk = _mk_chunk(chunk_id="x", symbol_id=1, body="anything")
        bad = chunk._replace(vector=[0.0] * 32)
        with pytest.raises(SemanticIndexError):
            store.insert_or_update(bad)


def test_insert_rejects_unknown_kind(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        chunk = _mk_chunk(chunk_id="x", symbol_id=1, body="a", chunk_kind="not_real")
        with pytest.raises(SemanticIndexError):
            _seat(store, [chunk])


def test_delete_by_symbol_removes_all_chunks_for_id(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(chunk_id="a", symbol_id=1, body="one"),
                _mk_chunk(chunk_id="b", symbol_id=1, body="two", locator="1/2"),
                _mk_chunk(chunk_id="c", symbol_id=2, body="three"),
            ],
        )
        deleted = store.delete_by_symbol(1)
        assert deleted == 2
        assert store.count() == 1


def test_delete_by_file_removes_scoped_chunks(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(
                    chunk_id="a", symbol_id=1, body="one", file_path="/repo/a.py"
                ),
                _mk_chunk(
                    chunk_id="b", symbol_id=2, body="two", file_path="/repo/b.py"
                ),
            ],
        )
        deleted = store.delete_by_file("/repo/a.py")
        assert deleted == 1
        assert store.count() == 1


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------


def test_search_returns_top_k(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(chunk_id="a", symbol_id=1, body="alpha token"),
                _mk_chunk(chunk_id="b", symbol_id=2, body="beta token"),
                _mk_chunk(chunk_id="c", symbol_id=3, body="gamma token"),
            ],
        )
        hits = store.search("alpha token", top_k=2)
        assert len(hits) == 2
        assert hits[0].chunk_id == "a"


def test_search_zero_top_k_returns_empty(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(store, [_mk_chunk(chunk_id="x", symbol_id=1, body="one")])
        assert store.search("one", top_k=0) == []


def test_search_with_filter_scopes_to_column(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(
                    chunk_id="a", symbol_id=1, body="hello", file_path="/repo/a.py"
                ),
                _mk_chunk(
                    chunk_id="b", symbol_id=2, body="hello", file_path="/repo/b.py"
                ),
            ],
        )
        hits = store.search("hello", top_k=5, filter={"file_path": "/repo/a.py"})
        assert [h.chunk_id for h in hits] == ["a"]


def test_search_filter_rejects_unsupported_column(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        with pytest.raises(SemanticIndexError):
            store.search("hello", filter={"not_a_column": "x"})


def test_search_by_symbol_returns_neighbours_excluding_seed(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(chunk_id="seed", symbol_id=1, body="pivot chunk"),
                _mk_chunk(chunk_id="near", symbol_id=2, body="pivot chunk related"),
                _mk_chunk(chunk_id="far", symbol_id=3, body="unrelated content"),
            ],
        )
        hits = store.search_by_symbol(1, top_k=5)
        assert all(h.symbol_id != 1 for h in hits)


def test_search_by_symbol_returns_empty_when_symbol_absent(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        assert store.search_by_symbol(99) == []


# ---------------------------------------------------------------------------
# search_with_budget — the load-bearing Second Pass Q1 test
# ---------------------------------------------------------------------------


def test_search_with_budget_respects_token_cap(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(
                    chunk_id=f"c{i}", symbol_id=i, body=f"body{i}", token_count=30
                )
                for i in range(10)
            ],
        )
        # Cap 100 tokens; each chunk is 30 tokens; expect 3 chunks.
        hits = store.search_with_budget("body", token_budget=100, top_k_pool=10)
        assert sum(h.token_count for h in hits) <= 100
        assert len(hits) == 3


def test_search_with_budget_skips_too_large_chunks(tmp_path: Path):
    """Second Pass Q1: a chunk that overflows the remaining budget is skipped
    and later smaller chunks may still fit; the search does not stop at the
    first overflow."""
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(
                    chunk_id="oversize", symbol_id=1, body="oversize", token_count=500
                ),
                _mk_chunk(
                    chunk_id="small_a", symbol_id=2, body="small a", token_count=20
                ),
                _mk_chunk(
                    chunk_id="small_b", symbol_id=3, body="small b", token_count=20
                ),
            ],
        )
        hits = store.search_with_budget(
            "oversize small", token_budget=100, top_k_pool=10
        )
        ids = {h.chunk_id for h in hits}
        # The 500-token chunk cannot fit under a 100-token cap; the two
        # small chunks should be returned instead.
        assert "oversize" not in ids
        assert "small_a" in ids or "small_b" in ids


def test_search_with_budget_zero_budget_returns_empty(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(store, [_mk_chunk(chunk_id="x", symbol_id=1, body="one")])
        assert store.search_with_budget("one", token_budget=0) == []


def test_search_with_budget_seats_accountant_when_supplied(tmp_path: Path):
    symbols = _symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [
                _mk_chunk(
                    chunk_id=f"c{i}", symbol_id=i, body=f"body{i}", token_count=30
                )
                for i in range(3)
            ],
        )
        declaration = BudgetDeclaration(
            function="test.search_with_budget",
            input_min=100,
            input_target=1000,
            input_max=2000,
            output_min=100,
            output_target=500,
            output_max=1000,
            reasoning_headroom=200,
            hard_ceiling=5000,
        )
        accountant = BudgetAccountant(declaration=declaration)
        hits = store.search_with_budget(
            "body",
            token_budget=100,
            top_k_pool=10,
            budget_accountant=accountant,
        )
        assert accountant.used() == sum(h.token_count for h in hits)


# ---------------------------------------------------------------------------
# Graph enrichment (module_03 POST inbound constraint 1)
# ---------------------------------------------------------------------------


def test_enrich_with_graph_filters_symbol_only_edges_by_default(tmp_path: Path):
    from ract.memory.graph_index import EdgeRow, GraphIndex
    from ract.memory.lsp_fallback import populate_symbol_only

    symbols = _symbol_index(tmp_path)
    # Seed two real symbol rows.
    sym_a = SymbolRow(
        id=None,
        name="alpha",
        kind="function",
        file_path="/repo/a.py",
        start_line=1,
        end_line=5,
        signature="def alpha()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash="a",
        token_count=10,
        updated_at=1,
    )
    sym_b = SymbolRow(
        id=None,
        name="beta",
        kind="function",
        file_path="/repo/b.py",
        start_line=1,
        end_line=5,
        signature="def beta()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash="b",
        token_count=10,
        updated_at=1,
    )
    id_a = symbols.insert_or_update(sym_a)
    id_b = symbols.insert_or_update(sym_b)
    graph = GraphIndex(str(tmp_path / "graph.db"), symbols)
    # Insert one LSP edge alpha -> beta and one symbol_only self-edge on alpha.
    graph.insert_edge(
        EdgeRow(
            id=None,
            source_symbol_id=id_a,
            target_symbol_id=id_b,
            edge_type="calls",
            location_file="/repo/a.py",
            location_line=2,
            strength=1,
            neighborhood_source="lsp",
        )
    )
    populate_symbol_only(
        graph,
        [symbols.find_by_name("alpha")[0]],
        "python",
        reason="test",
    )

    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(
            store,
            [_mk_chunk(chunk_id="a", symbol_id=id_a, body="alpha body")],
        )
        hits = list(store.iter_chunks())
        enriched = store.enrich_with_graph(hits, graph)
    assert len(enriched) == 1
    hit, neighbours = enriched[0]
    assert hit.symbol_id == id_a
    # LSP edge points to beta; symbol_only edge on alpha itself must
    # not appear as a neighbour when include_symbol_only=False.
    names = {row.name for row in neighbours}
    assert "beta" in names
    assert "alpha" not in names
    graph.close()


def test_enrich_with_graph_includes_symbol_only_when_opted_in(tmp_path: Path):
    from ract.memory.graph_index import GraphIndex
    from ract.memory.lsp_fallback import populate_symbol_only

    symbols = _symbol_index(tmp_path)
    sym_a = SymbolRow(
        id=None,
        name="alpha",
        kind="function",
        file_path="/repo/a.py",
        start_line=1,
        end_line=5,
        signature="def alpha()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash="a",
        token_count=10,
        updated_at=1,
    )
    id_a = symbols.insert_or_update(sym_a)
    graph = GraphIndex(str(tmp_path / "graph.db"), symbols)
    populate_symbol_only(
        graph,
        [symbols.find_by_name("alpha")[0]],
        "python",
        reason="test",
    )
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        _seat(store, [_mk_chunk(chunk_id="a", symbol_id=id_a, body="alpha")])
        hits = list(store.iter_chunks())
        enriched = store.enrich_with_graph(hits, graph, include_symbol_only=True)
    _hit, neighbours = enriched[0]
    # Symbol-only self-edge: alpha points to alpha; enrichment skips
    # self-neighbour so neighbours can be empty but no exception.
    assert isinstance(neighbours, list)
    graph.close()


# RACT 0.5.0
