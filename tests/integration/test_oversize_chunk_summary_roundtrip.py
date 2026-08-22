"""Integration test: oversize sub-chunk → SUMMARY format round-trip.

Module_05 SP amendment (nemotron_ultra Q10 item 6). The pre-amendment
test surface asserted SUMMARY formatting and oversize marking
separately but not the composed path — an oversize function body
passed through :func:`ract.memory.chunker.chunk_symbol` then rendered
via :func:`ract.memory.chunk.format_chunk` in SUMMARY mode must
produce a deterministic body carrying at least a ``control:`` line
(and, when the body contains calls, a ``calls:`` line).

Also verifies the SP amendment 5 fix: language inferred from
``ChunkRow.file_path`` suffix so the SUMMARY control-flow catalogue
selects the correct language when the retrieval path re-hydrates a
:class:`Chunk` from a :class:`ChunkRow`.
"""

from __future__ import annotations

import warnings

from ract.memory.chunk import ChunkFormat, chunk_from_chunk_row, format_chunk
from ract.memory.chunker import (
    MAX_TOKENS_PER_CHUNK,
    OVERSIZE_WARNING_KEY,
    chunk_symbol,
)
from ract.memory.symbol_index import SymbolRow


def _big_python_row(body: str) -> SymbolRow:
    return SymbolRow(
        id=1,
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
        updated_at=1,
    )


def _big_typescript_row(body: str) -> SymbolRow:
    return SymbolRow(
        id=2,
        name="loop",
        kind="function",
        file_path="/repo/src/loop.ts",
        start_line=1,
        end_line=body.count("\n"),
        signature="function loop(items: number[]): number",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="typescript",
        content_hash=None,
        token_count=None,
        updated_at=1,
    )


def test_oversize_python_sub_chunk_summary_carries_control_line() -> None:
    """End-to-end: chunk a large Python function, take a sub-chunk,
    format as SUMMARY, verify deterministic body content.
    """
    lines = ["def big():"]
    for i in range(200):
        lines.append(f"    x{i} = compute({i}, {i}, {i})")
    lines.append("    for i in range(10):")
    for i in range(200):
        lines.append(f"        y{i} = handle({i})")
    body = "\n".join(lines) + "\n"

    row = _big_python_row(body)
    chunks = chunk_symbol(row, body)
    assert len(chunks) >= 2

    # Round-trip: ChunkRow → Chunk (via chunk_from_chunk_row) →
    # format_chunk(SUMMARY).
    for chunk_row in chunks:
        chunk = chunk_from_chunk_row(chunk_row)
        # Amendment 5 fix: language inferred from .py suffix.
        assert chunk.language == "python"
        summary_chunk = format_chunk(chunk, ChunkFormat.SUMMARY)
        assert summary_chunk.body != "summary unavailable"
        assert "control:" in summary_chunk.body
        assert summary_chunk.summary_pending is False


def test_oversize_typescript_sub_chunk_summary_uses_ts_catalogue() -> None:
    """Amendment 5 correctness: TS body's SUMMARY control-flow line
    reflects the TS keyword catalogue (has ``catch``/``switch`` in
    the vocabulary) rather than the Python default.

    Guards against the pre-amendment behaviour where
    ``chunk_from_chunk_row`` set ``language=None`` and every SUMMARY
    dispatched to Python control-flow counters.
    """
    body_lines = [
        "function pipeline(events: Event[]): Result {",
        "  let acc = init();",
    ]
    # Push over the token cap.
    for i in range(300):
        body_lines.append(f"  acc = step_{i}(acc, events[{i}]);")
    body_lines.append("  try {")
    body_lines.append("    validate(acc);")
    body_lines.append("  } catch (err) {")
    body_lines.append("    fallback(err);")
    body_lines.append("  }")
    body_lines.append("  return acc;")
    body_lines.append("}")
    body = "\n".join(body_lines) + "\n"

    row = _big_typescript_row(body)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chunks = chunk_symbol(row, body)
    assert len(chunks) >= 1

    # Verify the language-inference amendment on chunk_from_chunk_row.
    chunk = chunk_from_chunk_row(chunks[0])
    assert chunk.language == "typescript"

    # Now render SUMMARY; must NOT crash and must include some
    # control-flow marker (even if the specific sub-chunk this
    # iteration draws doesn't include the try/catch, it always has a
    # `control:` line).
    summary_chunk = format_chunk(chunk, ChunkFormat.SUMMARY)
    assert "control:" in summary_chunk.body
    assert summary_chunk.summary_pending is False


def test_oversize_locator_survives_summary_round_trip() -> None:
    """Amendment 3 discipline: oversize marker in the locator is
    preserved across ``chunk_symbol`` → ``chunk_from_chunk_row`` →
    ``format_chunk(SUMMARY)``. The SUMMARY rendering must not silently
    strip the oversize handshake (module_04 POST inbound constraint 2).
    """
    huge_word_line = " ".join(f"tok{i}" for i in range(4000))
    body = f"def huge():\n    return ({huge_word_line})\n"
    row = _big_python_row(body)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chunks = chunk_symbol(row, body)
    # At least one oversize sub-chunk marker.
    oversize_chunks = [
        c for c in chunks if c.chunk_locator.startswith(OVERSIZE_WARNING_KEY)
    ]
    assert oversize_chunks, "expected at least one oversize sub-chunk"

    chunk = chunk_from_chunk_row(oversize_chunks[0])
    assert chunk.oversize is True

    summary_chunk = format_chunk(chunk, ChunkFormat.SUMMARY)
    # Oversize flag preserved through SUMMARY rendering.
    assert summary_chunk.oversize is True
    assert summary_chunk.chunk_locator == chunk.chunk_locator


def test_infer_language_from_path_suffixes() -> None:
    """SP amendment guard: language inference table stays in sync with
    the shipped chunkers. If a new language chunker lands, add its
    suffix here so its ChunkRows do not silently fall back to Python
    control-flow counters."""
    from ract.memory.chunk import _infer_language_from_path

    assert _infer_language_from_path("/repo/src/mod.py") == "python"
    assert _infer_language_from_path("/repo/src/types.pyi") == "python"
    assert _infer_language_from_path("/repo/src/app.ts") == "typescript"
    assert _infer_language_from_path("/repo/src/app.tsx") == "typescript"
    assert _infer_language_from_path("/repo/src/app.js") == "javascript"
    assert _infer_language_from_path("/repo/src/app.jsx") == "javascript"
    assert _infer_language_from_path("/repo/src/app.mjs") == "javascript"
    assert _infer_language_from_path("/repo/src/app.cjs") == "javascript"
    assert _infer_language_from_path("/repo/src/lib.rs") == "rust"
    assert _infer_language_from_path("/repo/src/main.go") == "go"
    # Unknown suffixes preserve pre-amendment behaviour.
    assert _infer_language_from_path("/repo/src/Main.java") is None
    assert _infer_language_from_path("/repo/README.md") is None


# RACT 0.5.1
