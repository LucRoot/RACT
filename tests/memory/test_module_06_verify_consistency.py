"""v0.5.2 hardening module_06 -- cross-index verify-consistency.

Master spec: ``docs/RACT_v0.5.2_HARDENING_SPEC.md`` §5 module_06
"Memory system polish".

Under test: :func:`ract.memory.verify_consistency.verify_indexes`
+ :class:`IndexConsistencyReport` + :class:`IndexInconsistency`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.graph_index import EdgeRow, GraphIndex
from ract.memory.symbol_index import SymbolIndex, SymbolRow
from ract.memory.verify_consistency import (
    IndexConsistencyReport,
    IndexInconsistency,
    verify_indexes,
)


def _sym(**kw) -> SymbolRow:
    defaults = dict(
        id=None,
        name="",
        kind="function",
        file_path="",
        start_line=None,
        end_line=None,
        signature="",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )
    defaults.update(kw)
    return SymbolRow(**defaults)


# ---------------------------------------------------------------------------
# Dataclass shape invariants
# ---------------------------------------------------------------------------


class TestReportShape:
    def test_consistent_factory(self) -> None:
        r = IndexConsistencyReport.consistent(
            symbols_checked=5, edges_checked=3, semantic_slices_checked=0
        )
        assert r.status == "CONSISTENT"
        assert r.is_consistent
        assert r.inconsistencies == ()

    def test_inconsistent_factory(self) -> None:
        r = IndexConsistencyReport.inconsistent(
            symbols_checked=5,
            edges_checked=3,
            semantic_slices_checked=0,
            inconsistencies=(
                IndexInconsistency(
                    kind="orphan_edge",
                    file="/repo/a.py",
                    symbol_id=42,
                    edge_id=7,
                    detail="synthetic",
                ),
            ),
        )
        assert r.status == "INCONSISTENT"
        assert not r.is_consistent
        assert len(r.inconsistencies) == 1

    def test_unavailable_factory(self) -> None:
        r = IndexConsistencyReport.unavailable(reason="db missing")
        assert r.status == "UNAVAILABLE"
        assert not r.is_consistent

    def test_status_consistent_with_details_is_refused(self) -> None:
        with pytest.raises(ValueError, match="contradictory"):
            IndexConsistencyReport(
                status="CONSISTENT",
                symbols_checked=1,
                edges_checked=0,
                semantic_slices_checked=0,
                inconsistencies=(
                    IndexInconsistency(
                        kind="orphan_edge",
                        file=None,
                        symbol_id=None,
                        edge_id=None,
                        detail="x",
                    ),
                ),
            )

    def test_status_inconsistent_without_details_is_refused(self) -> None:
        with pytest.raises(ValueError, match="requires at least one"):
            IndexConsistencyReport(
                status="INCONSISTENT",
                symbols_checked=1,
                edges_checked=0,
                semantic_slices_checked=0,
                inconsistencies=(),
            )

    def test_illegal_status_refused(self) -> None:
        with pytest.raises(ValueError, match="status must be"):
            IndexConsistencyReport(
                status="BOGUS",
                symbols_checked=0,
                edges_checked=0,
                semantic_slices_checked=0,
            )

    def test_illegal_inconsistency_kind_refused(self) -> None:
        with pytest.raises(ValueError, match="kind must be"):
            IndexInconsistency(
                kind="unknown",
                file=None,
                symbol_id=None,
                edge_id=None,
                detail="x",
            )


# ---------------------------------------------------------------------------
# Live index verify_indexes
# ---------------------------------------------------------------------------


class TestVerifyIndexesLive:
    def test_empty_symbol_index_reports_consistent(self) -> None:
        with SymbolIndex() as sym:
            r = verify_indexes(symbol_index=sym, check_files_on_disk=False)
            assert r.status == "CONSISTENT"
            assert r.symbols_checked == 0

    def test_none_symbol_index_reports_unavailable(self) -> None:
        r = verify_indexes(symbol_index=None)
        assert r.status == "UNAVAILABLE"
        assert "None" in r.reason

    def test_missing_symbol_file_flagged(self, tmp_path: Path) -> None:
        with SymbolIndex() as sym:
            # Real file exists.
            good = tmp_path / "good.py"
            good.write_text("x = 1\n", encoding="utf-8")
            sym.insert_or_update(
                _sym(
                    name="x",
                    kind="constant",
                    file_path=str(good),
                    content_hash="g",
                )
            )
            # Ghost file does NOT exist.
            ghost = tmp_path / "ghost.py"
            sym.insert_or_update(
                _sym(
                    name="y",
                    kind="constant",
                    file_path=str(ghost),
                    content_hash="h",
                )
            )
            r = verify_indexes(symbol_index=sym, check_files_on_disk=True)
            assert r.status == "INCONSISTENT"
            assert any(
                i.kind == "missing_symbol_file" and i.file == str(ghost)
                for i in r.inconsistencies
            )
            # The existing file does NOT get flagged.
            assert not any(i.file == str(good) for i in r.inconsistencies)

    def test_no_disk_check_skips_missing_file(self, tmp_path: Path) -> None:
        with SymbolIndex() as sym:
            sym.insert_or_update(
                _sym(
                    name="x",
                    kind="constant",
                    file_path=str(tmp_path / "ghost.py"),
                    content_hash="g",
                )
            )
            r = verify_indexes(symbol_index=sym, check_files_on_disk=False)
            assert r.status == "CONSISTENT"

    def test_orphan_edge_flagged(self, tmp_path: Path) -> None:
        with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as graph:
            good = tmp_path / "good.py"
            good.write_text("def f(): pass\n", encoding="utf-8")
            sid = sym.insert_or_update(
                _sym(
                    name="f",
                    kind="function",
                    file_path=str(good),
                    content_hash="f",
                )
            )
            # Insert an edge where target references a non-existent
            # symbol id.
            graph.insert_edge(
                EdgeRow(
                    id=None,
                    source_symbol_id=sid,
                    target_symbol_id=99999,
                    edge_type="calls",
                    location_file=str(good),
                    location_line=1,
                    strength=1,
                    neighborhood_source="lsp",
                )
            )
            r = verify_indexes(
                symbol_index=sym,
                graph_index=graph,
                check_files_on_disk=False,
            )
            assert r.status == "INCONSISTENT"
            assert any(
                i.kind == "orphan_edge" and i.symbol_id == 99999
                for i in r.inconsistencies
            )
            assert r.edges_checked >= 1

    def test_dangling_edge_location_flagged(self, tmp_path: Path) -> None:
        with SymbolIndex() as sym, GraphIndex(symbol_index=sym) as graph:
            good = tmp_path / "good.py"
            good.write_text("def f(): pass\n", encoding="utf-8")
            sid = sym.insert_or_update(
                _sym(
                    name="f",
                    kind="function",
                    file_path=str(good),
                    content_hash="f",
                )
            )
            graph.insert_edge(
                EdgeRow(
                    id=None,
                    source_symbol_id=sid,
                    target_symbol_id=sid,
                    edge_type="calls",
                    # Location file NOT indexed by symbol_index.
                    location_file="/does/not/exist_anywhere.py",
                    location_line=1,
                    strength=1,
                    neighborhood_source="lsp",
                )
            )
            r = verify_indexes(
                symbol_index=sym,
                graph_index=graph,
                check_files_on_disk=False,
            )
            assert any(i.kind == "dangling_edge_location" for i in r.inconsistencies)

    def test_max_inconsistencies_truncates(self, tmp_path: Path) -> None:
        with SymbolIndex() as sym:
            # Enqueue 20 ghost files.
            for i in range(20):
                sym.insert_or_update(
                    _sym(
                        name=f"g{i}",
                        kind="constant",
                        file_path=str(tmp_path / f"ghost_{i}.py"),
                        content_hash=f"h{i}",
                    )
                )
            r = verify_indexes(
                symbol_index=sym,
                check_files_on_disk=True,
                max_inconsistencies=5,
            )
            assert r.status == "INCONSISTENT"
            assert len(r.inconsistencies) == 5
            # The truncation shows up in the reason.
            assert "truncated" in r.reason


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class TestCliVerbWiring:
    def test_verify_consistency_missing_db_returns_2(
        self, tmp_path: Path, capsys
    ) -> None:
        from ract.memory.cli_memory import memory_command

        rc = memory_command(
            [
                "verify-consistency",
                str(tmp_path),
                "--no-disk-check",
            ]
        )
        assert rc == 2
        out = capsys.readouterr().out
        assert "UNAVAILABLE" in out

    def test_verify_consistency_json_output(self, tmp_path: Path, capsys) -> None:
        # Populate a real symbols.db so the verify runs.
        import json

        db_dir = tmp_path / ".ract" / "memory"
        db_dir.mkdir(parents=True, exist_ok=True)
        with SymbolIndex(db_path=str(db_dir / "symbols.db")):
            pass  # schema apply is enough
        from ract.memory.cli_memory import memory_command

        rc = memory_command(
            [
                "verify-consistency",
                str(tmp_path),
                "--no-disk-check",
                "--json",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["status"] == "CONSISTENT"
        assert payload["symbols_checked"] == 0
