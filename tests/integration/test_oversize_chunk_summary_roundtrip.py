"""Integration test: oversize sub-chunk → SUMMARY format round-trip.

Module_05 SP amendment (cross-family SP reviewer Q10 item 6). The pre-amendment
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


def test_oversize_composed_summary_carries_calls_line() -> None:
    """Amendment 4 (cross-family SP reviewer Q10 item 6): the composed path
    ``chunk_symbol`` (oversize) → ``format_chunk(SUMMARY)`` on a body
    that contains explicit external calls MUST surface a
    ``calls:`` line (in addition to ``control:``). The pre-amendment
    surface asserted SUMMARY formatting and oversize marking
    separately; this locks the round-trip.
    """
    lines = ["def worker(events):"]
    # Repeated call targets so the summary has something to surface.
    for i in range(220):
        lines.append(f"    result_{i} = compute({i})")
        lines.append(f"    log_event(result_{i})")
    lines.append("    for evt in events:")
    lines.append("        handle(evt)")
    body = "\n".join(lines) + "\n"

    row = _big_python_row(body)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chunks = chunk_symbol(row, body)
    assert len(chunks) >= 2

    # At least one sub-chunk's SUMMARY body must carry BOTH the
    # `control:` line and the `calls:` line — proves the composed
    # path fires (not just SUMMARY formatting or oversize marking
    # separately).
    saw_control_and_calls = False
    for chunk_row in chunks:
        chunk = chunk_from_chunk_row(chunk_row)
        summary_chunk = format_chunk(chunk, ChunkFormat.SUMMARY)
        if "control:" in summary_chunk.body and "calls:" in summary_chunk.body:
            saw_control_and_calls = True
            break
    assert saw_control_and_calls, (
        "expected at least one composed oversize→SUMMARY round-trip "
        "to surface both control: and calls: markers"
    )


def test_sub_chunk_method_surfaced_on_chunkrow_and_chunk() -> None:
    """Amendment 1 (cross-family SP reviewer Q10 item 1): ``sub_chunk_method``
    must be observable on the emitted :class:`ChunkRow` and on the
    :class:`Chunk` derived via :func:`chunk_from_chunk_row`. Pre-
    amendment the value was ``del sub_method``'d in chunk_symbol and
    downstream had no way to observe which splitter fired.
    """
    from ract.memory.chunker import SUB_CHUNK_METHOD_AST

    # Python body large enough to split, with AST-parseable structure
    # so the dispatcher picks the AST path.
    lines = ["def big():"]
    for i in range(200):
        lines.append(f"    x{i} = compute({i})")
    lines.append("    if True:")
    for i in range(200):
        lines.append(f"        y{i} = handle({i})")
    body = "\n".join(lines) + "\n"

    row = _big_python_row(body)
    chunks = chunk_symbol(row, body)
    assert len(chunks) >= 2

    # Every emitted ChunkRow carries the AST method.
    for chunk_row in chunks:
        assert chunk_row.sub_chunk_method == SUB_CHUNK_METHOD_AST
        # Language threaded through from SymbolRow.
        assert chunk_row.language == "python"
        # And propagates onto the Chunk view.
        chunk = chunk_from_chunk_row(chunk_row)
        assert chunk.sub_chunk_method == SUB_CHUNK_METHOD_AST
        # And survives a SUMMARY format round-trip.
        summary_chunk = format_chunk(chunk, ChunkFormat.SUMMARY)
        assert summary_chunk.sub_chunk_method == SUB_CHUNK_METHOD_AST


def test_sub_chunk_method_none_on_unsplit_symbol() -> None:
    """Single-chunk (unsplit) symbols carry ``sub_chunk_method=None``
    because no splitter ran. Guards against a future refactor that
    populates the field on every row (which would blur the signal).
    """
    row = SymbolRow(
        id=99,
        name="tiny",
        kind="function",
        file_path="/repo/src/tiny.py",
        start_line=1,
        end_line=2,
        signature="def tiny()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=1,
    )
    small_body = "def tiny():\n    return 1\n"
    chunks = chunk_symbol(row, small_body)
    assert len(chunks) == 1
    assert chunks[0].sub_chunk_method is None
    # Language still threaded even on unsplit path.
    assert chunks[0].language == "python"


def test_defensive_end_lineno_walks_nested_control_flow() -> None:
    """Amendment 2 (cross-family SP reviewer Q10 item 2): the AST splitter
    resolves ``end_lineno`` via a recursive child walk. Verifies the
    helper directly against a nested-control-flow node whose outer
    ``end_lineno`` might be missing on some trees.
    """
    import ast

    from ract.memory.chunker import _resolve_end_lineno

    src = "if outer:\n    if middle:\n        if inner:\n            pass\n"
    tree = ast.parse(src)
    outer_if = tree.body[0]
    # Outer's end_lineno should reach line 4 (the innermost pass),
    # whether from outer.end_lineno or via the child walk.
    assert _resolve_end_lineno(outer_if) >= 4
    # Simulate a node with no end_lineno anywhere: build a bare Pass
    # with only lineno set; the helper must not crash and must
    # return at least lineno.

    class _NakedNode(ast.AST):
        _fields: tuple[str, ...] = ()

        def __init__(self, lineno: int) -> None:
            super().__init__()
            self.lineno = lineno

    naked = _NakedNode(lineno=17)
    assert _resolve_end_lineno(naked) == 17


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
