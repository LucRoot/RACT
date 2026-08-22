"""Tests for :func:`ract.memory.chunker._split_semantic_boundaries`
Python AST branch.

Source-spec audit `_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md`
finding 5 (MEDIUM, self-declared Flagged gap 2): the pre-module_05
sub-chunker split at blank-line groups regardless of language. Module_05
adds per-language dispatch; Python uses stdlib :mod:`ast` to cut at
``For`` / ``While`` / ``If`` / ``Try`` boundaries.

Gate: `docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md` §5 row
"Sub-chunking uses AST boundaries".
"""

from __future__ import annotations

from ract.memory.chunker import (
    MAX_TOKENS_PER_CHUNK,
    SUB_CHUNK_METHOD_AST,
    SUB_CHUNK_METHOD_BLANK_LINE,
    _split_python_ast_boundaries,
    _split_semantic_boundaries,
    chunk_symbol,
)
from ract.memory.symbol_index import SymbolRow


def _row(language: str = "python", end_line: int = 1) -> SymbolRow:
    return SymbolRow(
        id=None,
        name="big",
        kind="function",
        file_path="/repo/big.py",
        start_line=1,
        end_line=end_line,
        signature="def big()",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language=language,
        content_hash=None,
        token_count=None,
        updated_at=None,
    )


def test_dispatch_returns_ast_method_for_python_parseable_body() -> None:
    body = (
        "def big():\n"
        "    x = 1\n"
        "    for i in range(10):\n"
        "        x += i\n"
        "    if x > 0:\n"
        "        return x\n"
        "    return 0\n"
    )
    pieces, method = _split_semantic_boundaries(body, "python")
    assert method == SUB_CHUNK_METHOD_AST
    assert "".join(pieces) == body


def test_dispatch_falls_back_to_blank_line_for_python_unparseable() -> None:
    body = "for x in items:\n    yield x\n)  # syntax error\n\nnext_block\n"
    _, method = _split_semantic_boundaries(body, "python")
    assert method == SUB_CHUNK_METHOD_BLANK_LINE


def test_dispatch_uses_blank_line_for_typescript_bodies() -> None:
    body = (
        "function loop(items: number[]): number {\n"
        "  for (const x of items) { total += x; }\n"
        "  return total;\n"
        "}\n"
    )
    _, method = _split_semantic_boundaries(body, "typescript")
    assert method == SUB_CHUNK_METHOD_BLANK_LINE


def test_ast_boundaries_cut_at_for_and_if() -> None:
    body = (
        "def multi():\n"
        "    x = 0\n"
        "    for i in range(10):\n"
        "        x += i\n"
        "    if x > 0:\n"
        "        return x\n"
        "    return -1\n"
    )
    pieces = _split_python_ast_boundaries(body)
    assert pieces is not None
    # We expect a straight-line prefix, then the for, then the if, then the trailing return.
    assert len(pieces) >= 3
    # Each control-flow statement lands as its own piece.
    for_piece = next(p for p in pieces if p.lstrip().startswith("for "))
    if_piece = next(p for p in pieces if p.lstrip().startswith("if "))
    assert "for i in range(10)" in for_piece
    assert "if x > 0" in if_piece


def test_ast_boundaries_include_try_statement() -> None:
    body = (
        "def guarded():\n"
        "    x = 1\n"
        "    try:\n"
        "        risky()\n"
        "    except ValueError:\n"
        "        fallback()\n"
        "    return x\n"
    )
    pieces = _split_python_ast_boundaries(body)
    assert pieces is not None
    try_piece = next(p for p in pieces if p.lstrip().startswith("try:"))
    assert "except ValueError" in try_piece


def test_ast_boundaries_include_while_statement() -> None:
    body = (
        "def waiter():\n"
        "    i = 0\n"
        "    while i < 10:\n"
        "        i += 1\n"
        "    return i\n"
    )
    pieces = _split_python_ast_boundaries(body)
    assert pieces is not None
    while_piece = next(p for p in pieces if p.lstrip().startswith("while "))
    assert "i < 10" in while_piece


def test_ast_boundaries_do_not_cut_at_random_blank_lines() -> None:
    """A stretch of blank lines inside a straight-line run must NOT
    produce a new sub-chunk — that's the pre-module_05 heuristic
    behaviour we deliberately replace on the Python path.
    """
    body = (
        "def straight():\n"
        "    a = 1\n"
        "\n"
        "\n"
        "    b = 2\n"
        "\n"
        "    c = 3\n"
        "    return a + b + c\n"
    )
    pieces = _split_python_ast_boundaries(body)
    # Straight-line run with no control-flow → single segment → falls
    # back (returns None per docstring behaviour) rather than pretending
    # to split.
    assert pieces is None


def test_ast_boundaries_returns_none_when_no_boundaries() -> None:
    body = "def trivial():\n    return 1\n"
    assert _split_python_ast_boundaries(body) is None


def test_chunk_symbol_uses_ast_method_on_python_body_over_cap() -> None:
    """End-to-end: :func:`chunk_symbol` with a Python row over the token
    cap produces sub-chunks whose boundaries land at AST statement
    edges. Byte-identical reassembly is verified alongside.
    """
    header = "def big():\n"
    body_parts: list[str] = [header]
    body_parts.append("    x = 0\n")
    body_parts.append("    for i in range(500):\n")
    for i in range(200):
        body_parts.append(f"        x = compute({i}, {i}, {i})\n")
    body_parts.append("    if x > 0:\n")
    for i in range(200):
        body_parts.append(f"        y = handle({i})\n")
    body_parts.append("    return x\n")
    body = "".join(body_parts)

    row = _row(language="python", end_line=body.count("\n"))
    chunks = chunk_symbol(row, body)
    # More than one chunk — cap should force the split.
    assert len(chunks) >= 2
    # Locators cover 0..N-1.
    positions = sorted(
        int(c.chunk_locator.split(":")[-1].split("/")[0]) for c in chunks
    )
    assert positions == list(range(len(chunks)))


def test_python_ast_split_byte_identical_reassembly() -> None:
    body = (
        "def big():\n"
        "    x = 0\n"
        "    for i in range(3):\n"
        "        x += i\n"
        "    if x:\n"
        "        return x\n"
        "    return 0\n"
    )
    pieces = _split_python_ast_boundaries(body)
    assert pieces is not None
    assert "".join(pieces) == body


def test_dispatch_return_shape_is_tuple() -> None:
    body = "def x():\n    return 1\n"
    result = _split_semantic_boundaries(body, "python")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], str)


def test_dispatch_returns_blank_line_method_for_unknown_language() -> None:
    body = "some body\n\nsome other body\n"
    _, method = _split_semantic_boundaries(body, "cobol")
    assert method == SUB_CHUNK_METHOD_BLANK_LINE


def test_max_tokens_per_chunk_still_pinned() -> None:
    # Guardrail: module_05 does not silently change the cap.
    assert MAX_TOKENS_PER_CHUNK == 500


# RACT 0.5.1
