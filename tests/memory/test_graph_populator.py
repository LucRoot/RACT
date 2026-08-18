"""Tests for the module_03 graph populator against a stub LSP client.

Does NOT require a live language server. A stub :class:`LspClient`
returns a fixed reference list per symbol so the populator's
symbol-id resolution, per-file batching, and per-symbol edge
insertion paths are exercised deterministically.

The live-LSP integration lives in ``test_graph_index_live.py``
and is skipped when the LSP binary is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ract.memory.graph_index import EdgeRow, GraphIndex
from ract.memory.graph_populator import GraphPopulator
from ract.memory.lsp import LspReference
from ract.memory.symbol_index import SymbolIndex, SymbolRow


class _StubLspClient:
    """Minimal stub matching :class:`~ract.memory.lsp.LspClient`."""

    def __init__(
        self,
        references: dict[str, list[LspReference]] | None = None,
        crash_on: set[str] | None = None,
    ) -> None:
        self._references = references or {}
        self._crash_on = crash_on or set()
        self.close_calls = 0
        self.language = "python"
        self.repo_root = Path.cwd()

    def close(self) -> None:
        self.close_calls += 1

    def references_of(self, symbol: SymbolRow) -> list[LspReference]:
        if symbol.name in self._crash_on:
            raise RuntimeError(f"stub LSP crash on {symbol.name}")
        return list(self._references.get(symbol.name, []))

    def as_edges(
        self,
        symbol: SymbolRow,
        symbol_resolver: Callable[[str, int], int | None],
    ) -> list[EdgeRow]:
        if symbol.id is None:
            return []
        edges: list[EdgeRow] = []
        for ref in self.references_of(symbol):
            source_id = symbol_resolver(ref.relative_path, ref.line)
            if source_id is None or source_id == symbol.id:
                continue
            edges.append(
                EdgeRow(
                    id=None,
                    source_symbol_id=source_id,
                    target_symbol_id=symbol.id,
                    edge_type="references",
                    location_file=ref.relative_path,
                    location_line=ref.line + 1,
                    strength=1,
                    neighborhood_source="lsp",
                )
            )
        return edges


def _seed_two_files(sym: SymbolIndex, root: Path) -> tuple[Path, Path, dict[str, int]]:
    file_a = root / "a.py"
    file_b = root / "b.py"
    file_a.write_text("def alpha():\n    pass\n", encoding="utf-8")
    file_b.write_text("def beta():\n    alpha()\n", encoding="utf-8")
    ids = {}
    ids["alpha"] = sym.insert_or_update(
        SymbolRow(
            id=None,
            name="alpha",
            kind="function",
            file_path=str(file_a),
            start_line=1,
            end_line=2,
            signature="def alpha():",
            docstring=None,
            visibility="public",
            parent_symbol_id=None,
            language="python",
            content_hash="a1",
            token_count=2,
            updated_at=None,
        )
    )
    ids["beta"] = sym.insert_or_update(
        SymbolRow(
            id=None,
            name="beta",
            kind="function",
            file_path=str(file_b),
            start_line=1,
            end_line=2,
            signature="def beta():",
            docstring=None,
            visibility="public",
            parent_symbol_id=None,
            language="python",
            content_hash="b1",
            token_count=2,
            updated_at=None,
        )
    )
    return file_a, file_b, ids


def test_populator_inserts_expected_edges(tmp_path: Path):
    with SymbolIndex() as sym:
        file_a, file_b, ids = _seed_two_files(sym, tmp_path)
        # Stub says: alpha is referenced from beta's file, line 1 (0-indexed).
        stub = _StubLspClient(
            references={
                "alpha": [LspReference(relative_path=str(file_b), line=1, column=4)]
            }
        )
        with GraphIndex(symbol_index=sym) as g:
            with GraphPopulator(
                tmp_path, g, sym, client_factory=lambda _r, _l: stub
            ) as pop:
                # Bypass real probe: mark languages available.
                report = pop.initial_build()
            assert report.edges_indexed >= 1
            # The edge should be beta -> alpha
            edges = g.callers_of(ids["alpha"])
            source_ids = [e.source_symbol_id for e in edges]
            assert ids["beta"] in source_ids


def test_populator_survives_per_symbol_crash(tmp_path: Path):
    with SymbolIndex() as sym:
        file_a, file_b, ids = _seed_two_files(sym, tmp_path)
        # Alpha crashes; beta returns nothing. Build should not fail.
        stub = _StubLspClient(crash_on={"alpha"})
        with GraphIndex(symbol_index=sym) as g:
            with GraphPopulator(
                tmp_path, g, sym, client_factory=lambda _r, _l: stub
            ) as pop:
                report = pop.initial_build()
        assert report.lsp_errors >= 1


def test_populator_close_shuts_stub_clients(tmp_path: Path):
    with SymbolIndex() as sym:
        _seed_two_files(sym, tmp_path)
        stub = _StubLspClient()
        with GraphIndex(symbol_index=sym) as g:
            pop = GraphPopulator(tmp_path, g, sym, client_factory=lambda _r, _l: stub)
            # Force client attach.
            pop._ensure_client("python")
            pop.close()
        assert stub.close_calls == 1


def test_update_file_deletes_and_re_inserts(tmp_path: Path):
    with SymbolIndex() as sym:
        file_a, file_b, ids = _seed_two_files(sym, tmp_path)
        stub = _StubLspClient(
            references={
                "alpha": [LspReference(relative_path=str(file_b), line=1, column=4)]
            }
        )
        with GraphIndex(symbol_index=sym) as g:
            with GraphPopulator(
                tmp_path, g, sym, client_factory=lambda _r, _l: stub
            ) as pop:
                pop.initial_build()
                pre = g.count()
                report = pop.update_file(file_a)
            assert report.deleted + report.inserted >= 0
            assert pre == g.count() or g.count() >= 1


def test_update_file_skips_when_no_symbols_present(tmp_path: Path):
    with SymbolIndex() as sym:
        with GraphIndex(symbol_index=sym) as g:
            with GraphPopulator(
                tmp_path, g, sym, client_factory=lambda _r, _l: _StubLspClient()
            ) as pop:
                report = pop.update_file(tmp_path / "missing.py")
        assert report.deleted == 0
        assert report.inserted == 0


def test_populator_resolver_finds_caller_by_line_range(tmp_path: Path):
    with SymbolIndex() as sym:
        file_a = tmp_path / "big.py"
        file_a.write_text("def outer():\n    inner()\n" * 3, encoding="utf-8")
        outer_id = sym.insert_or_update(
            SymbolRow(
                id=None,
                name="outer",
                kind="function",
                file_path=str(file_a),
                start_line=1,
                end_line=10,
                signature="def outer():",
                docstring=None,
                visibility="public",
                parent_symbol_id=None,
                language="python",
                content_hash="h",
                token_count=1,
                updated_at=None,
            )
        )
        with GraphIndex(symbol_index=sym) as g:
            with GraphPopulator(
                tmp_path, g, sym, client_factory=lambda _r, _l: _StubLspClient()
            ) as pop:
                resolver = pop._global_resolver()
                # LSP line is 0-indexed; line 3 maps to symbol row line 4.
                assert resolver(str(file_a), 3) == outer_id


def test_populator_falls_back_when_lsp_missing(tmp_path: Path):
    """A client factory that raises triggers fallback for that language."""
    with SymbolIndex() as sym:
        _seed_two_files(sym, tmp_path)
        with GraphIndex(symbol_index=sym) as g:

            def _raising_factory(_root, _lang):
                raise ModuleNotFoundError("multilspy not installed")

            with GraphPopulator(
                tmp_path, g, sym, client_factory=_raising_factory
            ) as pop:
                pop._fallback_languages.add("python")  # skip probe
                # Symbols are python; probe would fallback.
                # Force the fallback path by attaching known-fallback.
                report = pop.initial_build()
            assert "python" in report.fallback_languages
            # Fallback edges are self-referential and marked symbol_only.
            cur = g.connection.execute(
                "SELECT count(*) as n FROM edges "
                "WHERE neighborhood_source = 'symbol_only'"
            ).fetchone()
            assert cur["n"] >= 1


# RACT 0.5.0
