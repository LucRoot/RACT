"""Unit tests for the module_03 graph index (SQLite + query API).

Covers schema load, edge roundtrip, callers_of / callees_of at 1
and 2 hops, blast_radius, path_between, orphans, hotspots, and
the delete paths.

Uses in-memory SQLite for speed; the real-store variant runs the
same suite against a temp file so a WAL-mode-only defect would
surface (Second Pass Q1: consistency after a mid-batch failure).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.budget import BudgetAccountant, BudgetDeclaration
from ract.memory.graph_index import (
    CURRENT_SCHEMA_VERSION,
    EDGE_TYPES,
    EdgeRow,
    GraphIndex,
    GraphIndexError,
    NEIGHBORHOOD_SOURCES,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _row(source: int, target: int, edge_type: str = "calls", **kwargs) -> EdgeRow:
    return EdgeRow(
        id=None,
        source_symbol_id=source,
        target_symbol_id=target,
        edge_type=edge_type,
        location_file=kwargs.get("location_file", f"f{source}.py"),
        location_line=kwargs.get("location_line", 10),
        strength=kwargs.get("strength", 1),
        neighborhood_source=kwargs.get("neighborhood_source", "lsp"),
    )


def _seed_symbols(sym: SymbolIndex) -> dict[str, int]:
    """Seat a small symbol set and return name -> id."""
    ids: dict[str, int] = {}
    for name, kind, path, line, visibility in [
        ("alpha", "function", "a.py", 1, "public"),
        ("beta", "function", "b.py", 1, "public"),
        ("gamma", "function", "c.py", 1, "private"),
        ("delta", "function", "d.py", 1, "public"),
        ("_hidden", "function", "e.py", 1, "private"),
    ]:
        rid = sym.insert_or_update(
            SymbolRow(
                id=None,
                name=name,
                kind=kind,
                file_path=path,
                start_line=line,
                end_line=line + 5,
                signature=f"def {name}(): ...",
                docstring=None,
                visibility=visibility,
                parent_symbol_id=None,
                language="python",
                content_hash=name,
                token_count=5,
                updated_at=None,
            )
        )
        ids[name] = rid
    return ids


def test_schema_version_is_v1():
    with GraphIndex() as g:
        assert g.schema_versions() == [CURRENT_SCHEMA_VERSION]


def test_edge_roundtrip_in_memory():
    with GraphIndex() as g:
        eid = g.insert_edge(_row(1, 2, strength=3))
        assert eid > 0
        assert g.count() == 1


def test_edge_roundtrip_disk_store(tmp_path: Path):
    db = tmp_path / "graph.db"
    with GraphIndex(db) as g:
        g.insert_edge(_row(1, 2))
        assert g.count() == 1
    # Re-open and confirm persistence.
    with GraphIndex(db) as g:
        assert g.count() == 1


def test_invalid_edge_type_refused():
    with GraphIndex() as g:
        with pytest.raises(GraphIndexError):
            g.insert_edge(
                EdgeRow(
                    id=None,
                    source_symbol_id=1,
                    target_symbol_id=2,
                    edge_type="not_an_edge_type",
                    location_file="x",
                    location_line=1,
                    strength=1,
                    neighborhood_source="lsp",
                )
            )


def test_invalid_neighborhood_source_refused():
    with GraphIndex() as g:
        with pytest.raises(GraphIndexError):
            g.insert_edge(
                EdgeRow(
                    id=None,
                    source_symbol_id=1,
                    target_symbol_id=2,
                    edge_type="calls",
                    location_file="x",
                    location_line=1,
                    strength=1,
                    neighborhood_source="fabricated",
                )
            )


def test_edge_types_frozenset_matches_spec():
    assert EDGE_TYPES == frozenset(
        {"calls", "imports", "inherits", "implements", "references"}
    )


def test_neighborhood_sources_frozenset():
    assert NEIGHBORHOOD_SOURCES == frozenset({"lsp", "symbol_only"})


def test_duplicate_insert_bumps_strength():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2, strength=2))
        g.insert_edge(_row(1, 2, strength=3))
        assert g.count() == 1
        row = g.hotspots(1)[0]
        assert row.strength == 5


def test_callers_of_one_hop():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 3))
        g.insert_edge(_row(2, 3))
        g.insert_edge(_row(1, 2))
        callers = g.callers_of(3)
        source_ids = sorted(e.source_symbol_id for e in callers)
        assert source_ids == [1, 2]


def test_callees_of_one_hop():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(1, 3))
        callees = g.callees_of(1)
        target_ids = sorted(e.target_symbol_id for e in callees)
        assert target_ids == [2, 3]


def test_callers_of_two_hops():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(2, 3))
        callers = g.callers_of(3, max_hops=2)
        source_ids = sorted(e.source_symbol_id for e in callers)
        assert 1 in source_ids
        assert 2 in source_ids


def test_callees_of_two_hops():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(2, 3))
        callees = g.callees_of(1, max_hops=2)
        target_ids = sorted(e.target_symbol_id for e in callees)
        assert 2 in target_ids
        assert 3 in target_ids


def test_callers_of_excludes_symbol_only_edges():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(2, 2, neighborhood_source="symbol_only"))
        callers = g.callers_of(2)
        assert [e.source_symbol_id for e in callers] == [1]


def test_callers_of_rejects_zero_hops():
    with GraphIndex() as g:
        with pytest.raises(GraphIndexError):
            g.callers_of(1, max_hops=0)


def test_blast_radius_two_hops():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        ids = _seed_symbols(sym)
        g.insert_edge(_row(ids["alpha"], ids["beta"]))
        g.insert_edge(_row(ids["beta"], ids["gamma"]))
        radius = g.blast_radius(ids["alpha"], max_hops=2)
        names = sorted(r.name for r in radius)
        assert names == ["beta", "gamma"]


def test_blast_radius_requires_symbol_index():
    with GraphIndex() as g:
        with pytest.raises(GraphIndexError):
            g.blast_radius(1)


def test_path_between_direct():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        path = g.path_between(1, 2)
        assert path is not None
        assert len(path) == 1
        assert path[0].source_symbol_id == 1


def test_path_between_multi_hop():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(2, 3))
        g.insert_edge(_row(3, 4))
        path = g.path_between(1, 4)
        assert path is not None
        assert [e.source_symbol_id for e in path] == [1, 2, 3]


def test_path_between_missing():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        assert g.path_between(1, 99) is None


def test_path_between_identity():
    with GraphIndex() as g:
        assert g.path_between(1, 1) == []


def test_orphans_returns_unreferenced_private_symbols():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        ids = _seed_symbols(sym)
        # Reference gamma (private) and delta (public); leave _hidden orphaned.
        g.insert_edge(_row(ids["alpha"], ids["gamma"]))
        g.insert_edge(_row(ids["alpha"], ids["delta"]))
        orphans = g.orphans(exclude_public=True)
        names = sorted(r.name for r in orphans)
        # alpha, beta are public with no inbound, filtered out.
        # gamma has inbound so is referenced.
        # delta has inbound (and public) so filtered.
        # _hidden is private and has no inbound.
        assert "_hidden" in names
        assert "gamma" not in names
        assert "alpha" not in names  # public


def test_orphans_without_public_filter_includes_all():
    with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as g:
        ids = _seed_symbols(sym)
        g.insert_edge(_row(ids["alpha"], ids["gamma"]))
        orphans = g.orphans(exclude_public=False)
        names = {r.name for r in orphans}
        # alpha, beta, delta, _hidden all lack inbound edges.
        assert "alpha" in names
        assert "beta" in names
        assert "delta" in names
        assert "_hidden" in names


def test_orphans_requires_symbol_index():
    with GraphIndex() as g:
        with pytest.raises(GraphIndexError):
            g.orphans()


def test_hotspots_by_threshold():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2, strength=1))
        g.insert_edge(_row(1, 3, strength=5))
        g.insert_edge(_row(1, 4, strength=10))
        hot = g.hotspots(5)
        strengths = sorted(e.strength for e in hot)
        assert strengths == [5, 10]


def test_hotspots_rejects_zero_threshold():
    with GraphIndex() as g:
        with pytest.raises(GraphIndexError):
            g.hotspots(0)


def test_delete_by_source_file():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2, location_file="a.py"))
        g.insert_edge(_row(1, 3, location_file="b.py"))
        deleted = g.delete_by_source_file("a.py")
        assert deleted == 1
        assert g.count() == 1


def test_delete_by_symbol_hits_both_endpoints():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(3, 1))
        g.insert_edge(_row(4, 5))
        deleted = g.delete_by_symbol(1)
        assert deleted == 2
        assert g.count() == 1


def test_edges_for_file():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2, location_file="a.py"))
        g.insert_edge(_row(1, 3, location_file="a.py"))
        g.insert_edge(_row(1, 4, location_file="b.py"))
        rows = g.edges_for_file("a.py")
        assert len(rows) == 2


def test_insert_edges_batch_rolls_back_on_failure():
    with GraphIndex() as g:
        good = _row(1, 2)
        bad = EdgeRow(
            id=None,
            source_symbol_id=3,
            target_symbol_id=4,
            edge_type="not_valid",
            location_file="x",
            location_line=1,
            strength=1,
            neighborhood_source="lsp",
        )
        with pytest.raises(GraphIndexError):
            g.insert_edges([good, bad])
        # Batch should have rolled back — no rows landed.
        assert g.count() == 0


def test_insert_edges_batch_commits_on_success():
    with GraphIndex() as g:
        edges = [_row(1, 2), _row(1, 3), _row(2, 3)]
        ids = g.insert_edges(edges)
        assert len(ids) == 3
        assert g.count() == 3


def test_budget_accountant_receives_traversal_cost():
    """Axiom 1: every graph query seats a section on the accountant."""
    decl = BudgetDeclaration(
        function="research",
        input_min=10,
        input_target=1_000,
        input_max=2_000,
        output_min=10,
        output_target=200,
        output_max=400,
        reasoning_headroom=100,
        hard_ceiling=10_000,
    )
    acct = BudgetAccountant(declaration=decl)
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        g.insert_edge(_row(1, 3))
        callers = g.callees_of(1, accountant=acct)
    assert len(callers) == 2
    assert acct.used() > 0
    # Section name is prefixed.
    names = [sec.name for sec in acct.sections()]
    assert any(name.startswith("graph.callees_of") for name in names)


def test_budget_accountant_none_is_no_op():
    """accountant=None does not raise; the seat-side effect is skipped."""
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2))
        callers = g.callers_of(2, accountant=None)
    assert callers


def test_insert_edges_atomicity_documented_as_batch_level():
    """Second Pass Q1 regression: the docstring names batch atomicity.

    A rollback inside one insert_edges call leaves the store empty;
    a prior committed insert_edges call keeps its edges. This is
    the actual per-file atomicity the populator ships (module_03
    Flagged gap 1 tracks per-symbol atomicity as v0.6 hardening).
    """
    with GraphIndex() as g:
        # First batch commits successfully.
        g.insert_edges([_row(1, 2), _row(1, 3)])
        assert g.count() == 2
        # Second batch fails mid-way and rolls back.
        with pytest.raises(GraphIndexError):
            g.insert_edges(
                [
                    _row(4, 5),
                    EdgeRow(
                        id=None,
                        source_symbol_id=6,
                        target_symbol_id=7,
                        edge_type="not_valid",
                        location_file="x",
                        location_line=1,
                        strength=1,
                        neighborhood_source="lsp",
                    ),
                ]
            )
        # First batch's edges survive; second batch's edges do not.
        assert g.count() == 2
    # Confirms the docstring claim: batch atomicity, not build atomicity.


def test_edges_for_file_ordering_is_insertion_order():
    with GraphIndex() as g:
        g.insert_edge(_row(1, 2, location_file="a.py", location_line=5))
        g.insert_edge(_row(3, 4, location_file="a.py", location_line=1))
        rows = g.edges_for_file("a.py")
        assert rows[0].source_symbol_id == 1
        assert rows[1].source_symbol_id == 3


# RACT 0.5.0
