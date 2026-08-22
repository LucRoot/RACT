"""Tests for :mod:`ract.memory.chunk` — Chunk value type + format
conversion.
"""

from __future__ import annotations

from ract.memory.chunk import (
    Chunk,
    ChunkFormat,
    chunk_from_chunk_row,
    chunk_from_symbol,
    format_chunk,
)
from ract.memory.symbol_index import SymbolRow


def _sym(**overrides) -> SymbolRow:
    base = {
        "id": 7,
        "name": "greet",
        "kind": "function",
        "file_path": "/repo/src/mod.py",
        "start_line": 1,
        "end_line": 3,
        "signature": "def greet():",
        "docstring": None,
        "visibility": "public",
        "parent_symbol_id": None,
        "language": "python",
        "content_hash": "abc",
        "token_count": 4,
        "updated_at": 1,
    }
    base.update(overrides)
    return SymbolRow(**base)


def _chunk(**overrides) -> Chunk:
    base = {
        "chunk_id": "cid",
        "symbol_id": 7,
        "symbol_name": "greet",
        "file_path": "/repo/src/mod.py",
        "language": "python",
        "kind": "function_body",
        "signature": "def greet():",
        "body": "def greet():\n    return 1\n",
        "content_hash": "abc",
        "token_count": 8,
        "oversize": False,
        "chunk_locator": "0/1",
        "start_line": 1,
        "end_line": 3,
    }
    base.update(overrides)
    return Chunk(**base)


def test_chunk_from_symbol_slices_source():
    source = b"def greet():\n    return 1\n\ndef other():\n    pass\n"
    row = _sym(start_line=1, end_line=2)
    chunk = chunk_from_symbol(row, source)
    assert "greet" in chunk.body
    assert "other" not in chunk.body
    assert chunk.symbol_id == 7
    assert chunk.language == "python"
    assert chunk.metadata["source_index"] == "symbol"
    assert chunk.oversize is False


def test_format_chunk_full_preserves_body():
    chunk = _chunk()
    got = format_chunk(chunk, ChunkFormat.FULL)
    assert got.body == chunk.body
    assert got.token_count > 0


def test_format_chunk_signature_returns_signature_only():
    chunk = _chunk()
    got = format_chunk(chunk, ChunkFormat.SIGNATURE)
    assert got.body == "def greet():"
    assert got.token_count == len("def greet():".split())


def test_format_chunk_body_only_strips_prepended_signature():
    body = "def greet():\nreturn 1\n"
    chunk = _chunk(body=body, signature="def greet():")
    got = format_chunk(chunk, ChunkFormat.BODY_ONLY)
    assert not got.body.startswith("def greet():\n")
    assert "return 1" in got.body


def test_format_chunk_body_only_leaves_body_when_no_prefix():
    body = "return 1\n"
    chunk = _chunk(body=body)
    got = format_chunk(chunk, ChunkFormat.BODY_ONLY)
    assert got.body == body


def test_format_chunk_summary_without_provider_returns_deterministic_body():
    """Post-module_05: SUMMARY without provider returns an AST-
    deterministic body (was: ``"summary unavailable"`` placeholder).

    Contract locked here: the shipping SUMMARY path in v0.5.1 no longer
    emits the placeholder that Lens 1C finding 4 (MEDIUM) surfaced.
    :attr:`Chunk.summary_pending` is ``False`` whenever the
    deterministic summary body is non-empty. The Bonsai council model
    remains the v0.6 provider slot per ADR-0046.
    """
    chunk = _chunk()
    got = format_chunk(chunk, ChunkFormat.SUMMARY, provider=None)
    assert got.body != "summary unavailable"
    assert got.body.startswith("def greet():")
    assert "control:" in got.body
    assert got.summary_pending is False


def test_format_chunk_summary_with_provider_uses_provider():
    class FakeProvider:
        def summarize(self, chunk_arg: Chunk) -> str:
            return f"one-line: {chunk_arg.symbol_name}"

    chunk = _chunk()
    got = format_chunk(chunk, ChunkFormat.SUMMARY, provider=FakeProvider())
    assert got.body == "one-line: greet"
    assert got.summary_pending is False


def test_format_chunk_preserves_metadata_and_oversize():
    chunk = _chunk(oversize=True, metadata={"source_index": "semantic", "note": "x"})
    got = format_chunk(chunk, ChunkFormat.SIGNATURE)
    assert got.oversize is True
    assert got.metadata == {"source_index": "semantic", "note": "x"}


def test_chunk_from_chunk_row_marks_oversize_from_locator():
    class FakeChunkRow:
        chunk_id = "row1"
        symbol_id = 3
        file_path = "/repo/f.py"
        chunk_kind = "function_body"
        signature = "def f():"
        content_hash = "hash1"
        token_count = 5
        body = "body"
        chunk_locator = "oversize:1/3"
        start_line = 1
        end_line = 100

    got = chunk_from_chunk_row(FakeChunkRow())
    assert got.oversize is True
    assert got.chunk_locator == "oversize:1/3"
    assert got.metadata["source_index"] == "semantic"


def test_chunk_from_chunk_row_normal_locator():
    class FakeChunkRow:
        chunk_id = "row2"
        symbol_id = 4
        file_path = "/repo/g.py"
        chunk_kind = "function_body"
        signature = "def g():"
        content_hash = "hash2"
        token_count = 5
        body = "body"
        chunk_locator = "0/1"
        start_line = 1
        end_line = 3

    got = chunk_from_chunk_row(FakeChunkRow())
    assert got.oversize is False
