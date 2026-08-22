"""Tests for :mod:`ract.memory.semantic_builder` and cpu_fallback."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("lancedb")

from ract.memory.cpu_fallback import (
    LANCEDB_BACKEND_ENV_VAR,
    LanceDbProbeResult,
    probe_lancedb,
)
from ract.memory.embedding import SYNTHETIC_384_NAME, SyntheticHashEmbedding
from ract.memory.semantic_builder import (
    build_from_files,
    initial_build,
    update_symbol,
)
from ract.memory.semantic_index import SemanticIndex
from ract.memory.symbol_index import SymbolIndex


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tiny_repo" / "py_pkg"


def _seed_symbol_index(tmp_path: Path) -> tuple[SymbolIndex, Path]:
    """Copy the python fixture into a scratch dir and parse it."""
    from ract.memory.parser import parse_file

    scratch = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT, scratch)
    symbols = SymbolIndex(str(tmp_path / "symbols.db"))
    for path in scratch.rglob("*.py"):
        parsed = parse_file(path)
        parsed = [row._replace(file_path=str(path)) for row in parsed]
        symbols.replace_file(str(path), parsed)
    return symbols, scratch


# ---------------------------------------------------------------------------
# cpu_fallback
# ---------------------------------------------------------------------------


def test_probe_lancedb_returns_defined_result():
    result = probe_lancedb()
    assert isinstance(result, LanceDbProbeResult)
    assert result.backend in ("gpu", "cpu")


def test_probe_lancedb_env_override_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(LANCEDB_BACKEND_ENV_VAR, "cpu")
    result = probe_lancedb()
    assert result.backend == "cpu"


def test_probe_lancedb_reports_version(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(LANCEDB_BACKEND_ENV_VAR, raising=False)
    result = probe_lancedb()
    assert result.available is True
    assert result.version is not None


# ---------------------------------------------------------------------------
# initial_build
# ---------------------------------------------------------------------------


def test_initial_build_inserts_expected_chunk_count(tmp_path: Path):
    symbols, scratch = _seed_symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        report = initial_build(scratch, store, symbols)
        assert report.chunks_indexed >= 1
        assert report.symbols_visited == symbols.count()
        assert store.count() == report.chunks_indexed
        assert report.embed_errors == 0


def test_initial_build_progress_callback_receives_updates(tmp_path: Path):
    symbols, scratch = _seed_symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    calls: list[tuple[str, int, int]] = []

    def _hook(stage: str, done: int, total: int) -> None:
        calls.append((stage, done, total))

    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        initial_build(scratch, store, symbols, progress=_hook)
    assert calls
    stages = {c[0] for c in calls}
    assert "chunk" in stages


def test_initial_build_completes_under_30_seconds(tmp_path: Path):
    """Master spec DoD: initial_build on the python fixture in under 30s."""
    symbols, scratch = _seed_symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        report = initial_build(scratch, store, symbols)
    assert report.elapsed_ms < 30_000


def test_initial_build_populates_parent_symbol_id_for_methods(tmp_path: Path):
    """Module_03 POST inbound constraint 2."""
    # Craft a source file with a class containing methods.
    src = tmp_path / "repo"
    src.mkdir()
    (src / "cls.py").write_text(
        (
            "class Widget:\n"
            "    def __init__(self):\n"
            "        self.x = 0\n"
            "\n"
            "    def do_something(self):\n"
            "        return self.x\n"
        ),
        encoding="utf-8",
    )
    from ract.memory.parser import parse_file

    symbols = SymbolIndex(str(tmp_path / "symbols.db"))
    parsed = parse_file(src / "cls.py")
    parsed = [row._replace(file_path=str(src / "cls.py")) for row in parsed]
    symbols.replace_file(str(src / "cls.py"), parsed)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        report = initial_build(src, store, symbols)
    class_rows = symbols.find_by_name("Widget")
    assert class_rows
    class_id = class_rows[0].id
    method_rows = [
        row for row in symbols.find_in_file(str(src / "cls.py")) if row.kind == "method"
    ]
    # Every method row should now name its class as parent.
    for method in method_rows:
        assert method.parent_symbol_id == class_id
    assert report.parent_symbols_linked >= len(method_rows)


# ---------------------------------------------------------------------------
# update_symbol
# ---------------------------------------------------------------------------


def test_update_symbol_replaces_stale_chunks(tmp_path: Path):
    symbols, scratch = _seed_symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        initial_build(scratch, store, symbols)
        # Pick one symbol; edit its source; re-run update_symbol.
        add_rows = symbols.find_by_name("add")
        assert add_rows
        add = add_rows[0]
        # Modify the source file's `add` body.
        source_path = Path(add.file_path)
        original = source_path.read_text(encoding="utf-8")
        modified = original.replace("return a + b", "return a + b + 1")
        source_path.write_text(modified, encoding="utf-8")
        # Re-parse and update the symbol row's content_hash to reflect
        # the new body.
        from ract.memory.parser import parse_file

        parsed = parse_file(source_path)
        parsed = [row._replace(file_path=str(source_path)) for row in parsed]
        symbols.replace_file(str(source_path), parsed)
        refreshed = [
            row for row in symbols.find_in_file(str(source_path)) if row.name == "add"
        ]
        assert refreshed
        report = update_symbol(refreshed[0].id, store, symbols)
        assert report.inserted >= 1
        # The updated body must live under the symbol's chunk rows in
        # the store. Vector search against ``SyntheticHashEmbedding``
        # (a hash-derived fallback with no semantic meaning) is not a
        # reliable oracle for content freshness -- the cosine to
        # "return a + b + 1" is essentially random and top_k=5 can
        # omit the updated chunk on some platforms. Read the rows
        # for this symbol_id directly instead; the stale-chunks
        # invariant is that update_symbol deleted the old body and
        # inserted the new one.
        symbol_chunks = list(
            store.iter_chunks(filter={"symbol_id": int(refreshed[0].id)})
        )
        assert symbol_chunks, (
            "update_symbol reported inserted>=1 but no chunks landed under "
            f"symbol_id={refreshed[0].id}"
        )
        assert any("+ 1" in ch.body for ch in symbol_chunks), (
            "update_symbol left symbol chunks in place but none carry the "
            "updated body; stale-chunk invariant violated. Bodies: "
            f"{[ch.body[:60] for ch in symbol_chunks]}"
        )


def test_update_symbol_returns_zero_when_symbol_absent(tmp_path: Path):
    symbols, _ = _seed_symbol_index(tmp_path)
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        report = update_symbol(999_999, store, symbols)
        assert report.inserted == 0
        assert report.deleted == 0


# ---------------------------------------------------------------------------
# build_from_files
# ---------------------------------------------------------------------------


def test_build_from_files_populates_store(tmp_path: Path):
    scratch = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT, scratch)
    symbols = SymbolIndex(str(tmp_path / "symbols.db"))
    embedder = SyntheticHashEmbedding(dim=384, name=SYNTHETIC_384_NAME)
    with SemanticIndex(tmp_path / "sem", symbols, embedder) as store:
        report = build_from_files(list(scratch.rglob("*.py")), store, symbols)
        assert report.chunks_indexed >= 1
        assert store.count() == report.chunks_indexed


# RACT 0.5.0
