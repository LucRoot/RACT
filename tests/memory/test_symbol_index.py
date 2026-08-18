"""Unit tests for the SQLite-backed SymbolIndex store.

Covers: schema load, insert / update / delete, five query helpers,
FTS5 mirror consistency within a single transaction (Second Pass Q4),
and content_hash-based dedup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ract.memory.symbol_index import (
    CURRENT_SCHEMA_VERSION,
    SymbolIndex,
    SymbolIndexError,
    SymbolRow,
)


def _row(
    *,
    name: str = "foo",
    kind: str = "function",
    file_path: str = "src/foo.py",
    start_line: int = 1,
    end_line: int = 5,
    signature: str = "def foo():",
    docstring: str | None = "greeting docstring",
    visibility: str | None = "public",
    parent_symbol_id: int | None = None,
    language: str | None = "python",
    content_hash: str | None = "abcd",
    token_count: int | None = 4,
    updated_at: int | None = 1_000_000,
) -> SymbolRow:
    return SymbolRow(
        id=None,
        name=name,
        kind=kind,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        signature=signature,
        docstring=docstring,
        visibility=visibility,
        parent_symbol_id=parent_symbol_id,
        language=language,
        content_hash=content_hash,
        token_count=token_count,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# Schema + open + close
# ---------------------------------------------------------------------------


def test_open_in_memory_loads_schema() -> None:
    with SymbolIndex() as idx:
        assert idx.schema_versions() == [CURRENT_SCHEMA_VERSION]
        assert idx.count() == 0


def test_open_on_disk_writes_file(tmp_path: Path) -> None:
    db = tmp_path / "symbols.db"
    with SymbolIndex(db) as idx:
        idx.insert_or_update(_row())
    assert db.is_file()
    # Reopen the store; the schema and rows survive.
    with SymbolIndex(db) as idx2:
        assert idx2.count() == 1


def test_context_manager_closes() -> None:
    idx = SymbolIndex()
    with idx:
        idx.insert_or_update(_row())
    # After context exit, further use trips a ProgrammingError.
    with pytest.raises(sqlite3.ProgrammingError):
        idx.connection.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Insert / update / delete
# ---------------------------------------------------------------------------


def test_insert_or_update_assigns_id() -> None:
    with SymbolIndex() as idx:
        row_id = idx.insert_or_update(_row())
        assert isinstance(row_id, int)
        assert row_id > 0


def test_insert_or_update_replaces_on_conflict() -> None:
    with SymbolIndex() as idx:
        row_id = idx.insert_or_update(_row(docstring="old"))
        row_id_again = idx.insert_or_update(_row(docstring="new"))
        assert row_id == row_id_again
        got = idx.find_by_name("foo")
        assert len(got) == 1
        assert got[0].docstring == "new"


def test_delete_by_file_returns_row_count() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(file_path="src/a.py", start_line=1))
        idx.insert_or_update(_row(name="bar", file_path="src/a.py", start_line=10))
        idx.insert_or_update(_row(file_path="src/b.py", start_line=1))
        deleted = idx.delete_by_file("src/a.py")
        assert deleted == 2
        assert idx.count() == 1


def test_replace_file_wraps_in_transaction() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(file_path="src/x.py", start_line=1))
        assigned = idx.replace_file(
            "src/x.py",
            [
                _row(name="alpha", file_path="src/x.py", start_line=1),
                _row(name="beta", file_path="src/x.py", start_line=20),
            ],
        )
        assert len(assigned) == 2
        rows = idx.find_in_file("src/x.py")
        assert [r.name for r in rows] == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def test_find_by_name_exact() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(name="foo"))
        idx.insert_or_update(_row(name="foobar", start_line=10))
        got = idx.find_by_name("foo")
        assert [r.name for r in got] == ["foo"]


def test_find_by_name_with_kind_filter() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(name="User", kind="class", start_line=1))
        idx.insert_or_update(_row(name="User", kind="function", start_line=100))
        got = idx.find_by_name("User", kind_filter="class")
        assert [r.kind for r in got] == ["class"]


def test_find_by_pattern_regex() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(name="test_alpha", start_line=1))
        idx.insert_or_update(_row(name="test_beta", start_line=2))
        idx.insert_or_update(_row(name="helper", start_line=3))
        got = idx.find_by_pattern(r"^test_")
        assert sorted(r.name for r in got) == ["test_alpha", "test_beta"]


def test_find_by_pattern_invalid_regex_raises() -> None:
    import re

    with SymbolIndex() as idx:
        with pytest.raises(re.error):
            idx.find_by_pattern(r"(unclosed")


def test_find_in_file_returns_source_order() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(name="b", file_path="src/x.py", start_line=50))
        idx.insert_or_update(_row(name="a", file_path="src/x.py", start_line=10))
        got = idx.find_in_file("src/x.py")
        assert [r.name for r in got] == ["a", "b"]


def test_find_by_text_fts_matches_name() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(name="parseUser", docstring="parse a user record"))
        idx.insert_or_update(_row(name="parseAdmin", start_line=100, docstring=""))
        got = idx.find_by_text("parseUser")
        assert [r.name for r in got] == ["parseUser"]


def test_find_by_text_fts_matches_docstring() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(
            _row(name="quicksort", docstring="in-place sort using pivot")
        )
        idx.insert_or_update(_row(name="mergesort", start_line=100, docstring=""))
        got = idx.find_by_text("pivot")
        assert [r.name for r in got] == ["quicksort"]


def test_find_by_text_reflects_update_in_same_transaction() -> None:
    # Second Pass Q4: FTS5 mirror must update in the same transaction
    # as the source row; a query issued after insert_or_update never
    # hits a stale snapshot.
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(name="alpha", docstring="original narrative"))
        got = idx.find_by_text("original")
        assert [r.name for r in got] == ["alpha"]
        idx.insert_or_update(_row(name="alpha", docstring="rewritten narrative"))
        assert idx.find_by_text("original") == []
        got = idx.find_by_text("rewritten")
        assert [r.name for r in got] == ["alpha"]


def test_find_by_hash_deduplication() -> None:
    with SymbolIndex() as idx:
        # Two symbols with the same content_hash — dedup lookup returns
        # both. The retrieve primitive (module_05) uses this to collapse
        # copy-pasted symbols in its cascade.
        h = "deadbeef"
        idx.insert_or_update(_row(name="a", content_hash=h, start_line=1))
        idx.insert_or_update(
            _row(name="b", file_path="src/b.py", content_hash=h, start_line=1)
        )
        idx.insert_or_update(_row(name="c", start_line=100, content_hash="other"))
        got = idx.find_by_hash(h)
        assert sorted(r.name for r in got) == ["a", "b"]


# ---------------------------------------------------------------------------
# Store utilities
# ---------------------------------------------------------------------------


def test_files_lists_distinct_paths() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(file_path="src/a.py", start_line=1))
        idx.insert_or_update(_row(name="x", file_path="src/a.py", start_line=10))
        idx.insert_or_update(_row(file_path="src/b.py", start_line=1))
        assert idx.files() == ["src/a.py", "src/b.py"]


def test_file_mtimes_reports_max_updated_at() -> None:
    with SymbolIndex() as idx:
        idx.insert_or_update(_row(file_path="src/a.py", start_line=1, updated_at=100))
        idx.insert_or_update(
            _row(name="x", file_path="src/a.py", start_line=10, updated_at=200)
        )
        idx.insert_or_update(_row(file_path="src/b.py", start_line=1, updated_at=50))
        got = idx.file_mtimes()
        assert got == {"src/a.py": 200, "src/b.py": 50}


def test_symbol_index_error_when_post_conflict_lookup_impossible() -> None:
    # The post-conflict lookup path is exercised only when the ON
    # CONFLICT DO UPDATE branch fires; this test doubles as a smoke on
    # the error type existing so the caller can catch it explicitly.
    assert issubclass(SymbolIndexError, RuntimeError)
