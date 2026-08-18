"""Tests for :mod:`ract.memory.chunker` — chunk-symbol behaviour."""

from __future__ import annotations

import warnings


from ract.memory.chunker import (
    CHUNK_KIND_FUNCTION_BODY,
    CHUNK_KIND_FUNCTION_SUBRANGE,
    MAX_TOKENS_PER_CHUNK,
    OVERSIZE_WARNING_KEY,
    OversizeChunkWarning,
    chunk_symbol,
)
from ract.memory.symbol_index import SymbolRow


SMALL_SOURCE = (
    "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n"
)


def _row(
    *,
    kind: str = "function",
    name: str = "add",
    start: int = 1,
    end: int = 2,
    signature: str = "def add(a, b)",
) -> SymbolRow:
    return SymbolRow(
        id=None,
        name=name,
        kind=kind,
        file_path="/repo/src/mod.py",
        start_line=start,
        end_line=end,
        signature=signature,
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )


def test_chunk_symbol_small_function_produces_one_chunk():
    row = _row(start=1, end=2)
    chunks = chunk_symbol(row, SMALL_SOURCE)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_kind == CHUNK_KIND_FUNCTION_BODY
    assert chunk.chunk_locator == "0/1"
    assert "return a + b" in chunk.body
    assert chunk.token_count > 0


def test_chunk_symbol_preserves_source_lines_in_body():
    row = _row(start=1, end=2)
    chunks = chunk_symbol(row, SMALL_SOURCE)
    assert chunks[0].body.startswith("def add(a, b):")


def test_chunk_symbol_class_kind_maps_to_class_body_chunk():
    row = _row(kind="class", name="Widget", signature="class Widget")
    chunks = chunk_symbol(row, SMALL_SOURCE)
    assert chunks[0].chunk_kind == "class_body"


def test_chunk_symbol_deterministic_chunk_id_across_runs():
    row = _row()
    a = chunk_symbol(row, SMALL_SOURCE)
    b = chunk_symbol(row, SMALL_SOURCE)
    assert a[0].chunk_id == b[0].chunk_id


def test_chunk_symbol_body_change_changes_chunk_id():
    row_a = _row()
    changed_source = SMALL_SOURCE.replace("return a + b", "return a - b")
    a = chunk_symbol(row_a, SMALL_SOURCE)
    b = chunk_symbol(row_a, changed_source)
    assert a[0].chunk_id != b[0].chunk_id


def _big_function_source() -> tuple[str, SymbolRow]:
    """Return a synthetic function large enough to trigger sub-chunking."""
    header = "def big():\n"
    # Each block is separated by a blank line — logical boundaries.
    # 800 blocks x 1 statement = plenty of tokens over the 500 cap.
    blocks: list[str] = []
    for i in range(200):
        blocks.append(f"    x{i} = compute({i}, {i + 1}, {i + 2})")
        blocks.append("")
    body = header + "\n".join(blocks) + "\n"
    row = SymbolRow(
        id=None,
        name="big",
        kind="function",
        file_path="/repo/src/big.py",
        start_line=1,
        end_line=body.count("\n"),
        signature="def big()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )
    return body, row


def test_chunk_symbol_large_function_produces_multiple_sub_chunks():
    source, row = _big_function_source()
    chunks = chunk_symbol(row, source)
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_kind == CHUNK_KIND_FUNCTION_SUBRANGE
        assert chunk.chunk_locator.endswith(f"/{len(chunks)}")


def test_chunk_symbol_sub_chunks_prepend_parent_signature():
    source, row = _big_function_source()
    chunks = chunk_symbol(row, source)
    for chunk in chunks:
        assert chunk.body.splitlines()[0] == "def big()"


def test_chunk_symbol_sub_chunks_respect_token_cap_where_boundaries_allow():
    source, row = _big_function_source()
    chunks = chunk_symbol(row, source)
    overs = [c for c in chunks if c.token_count > MAX_TOKENS_PER_CHUNK]
    # Semantic boundaries + line-count fallback should keep the majority
    # under the cap. A residual oversize sub-chunk is allowed but must
    # be flagged (see the warning test below).
    assert len(overs) <= max(1, len(chunks) // 4)


def test_chunk_symbol_emits_warning_when_sub_chunk_exceeds_cap():
    # Construct a body whose logical splits still exceed the cap.
    huge_word_line = " ".join([f"tok{i}" for i in range(4000)])
    body = f"def huge():\n    return ({huge_word_line})\n"
    row = SymbolRow(
        id=None,
        name="huge",
        kind="function",
        file_path="/repo/src/huge.py",
        start_line=1,
        end_line=2,
        signature="def huge()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        chunks = chunk_symbol(row, body)
    assert len(chunks) >= 1
    # At least one sub-chunk must exceed the cap because a 4000-token
    # single expression cannot be split at blank-line or line-count
    # boundaries without breaking the parse.
    assert any(c.token_count > MAX_TOKENS_PER_CHUNK for c in chunks)
    assert any(c.chunk_locator.startswith(OVERSIZE_WARNING_KEY) for c in chunks)
    assert any(issubclass(w.category, OversizeChunkWarning) for w in caught)


def test_chunk_symbol_bytes_input_and_str_input_agree():
    row = _row()
    a = chunk_symbol(row, SMALL_SOURCE)
    b = chunk_symbol(row, SMALL_SOURCE.encode("utf-8"))
    assert a[0].body == b[0].body
    assert a[0].content_hash == b[0].content_hash


def test_chunk_symbol_no_signature_still_produces_chunk():
    row = _row(signature="")
    chunks = chunk_symbol(row, SMALL_SOURCE)
    assert chunks[0].signature == ""


# RACT 0.5.0
