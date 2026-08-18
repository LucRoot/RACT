"""AST-chunk builder for the v0.5.0 semantic index.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Chunk
discipline. The chunker takes one module_02
:class:`~ract.memory.symbol_index.SymbolRow` plus the raw source
bytes for its file and produces a list of
:class:`~ract.memory.semantic_index.ChunkRow` records. Most symbols
produce one chunk; symbols whose ``token_count`` exceeds
:data:`MAX_TOKENS_PER_CHUNK` produce multiple sub-chunks per the
"semantic sub-chunking" rule.

The chunker does NOT own vector embedding or storage. That is
:mod:`ract.memory.semantic_index` and :mod:`ract.memory.semantic_builder`.
Chunking is pure over ``(SymbolRow, source_bytes)`` so unit tests can
compose synthetic scenarios without an embedder or a LanceDB store.

Sub-chunk overflow behaviour (Second Pass Q3): when a single logical
sub-chunk still exceeds :data:`MAX_TOKENS_PER_CHUNK`, the chunker
emits it as-is with :data:`OVERSIZE_WARNING_KEY` set in the chunk
locator's metadata and issues a Python ``warnings.warn`` call named
:class:`OversizeChunkWarning`. The rationale: emit the sub-chunk so
retrieval can still surface the region; the SUMMARY chunking fallback
from master spec §Chunk overflow item 2 defers to module_05 (retrieve
primitive), where :func:`summarize_chunk` will call a provider.
"""

from __future__ import annotations

import hashlib
import time
import warnings
from typing import TYPE_CHECKING

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.parser import estimate_tokens
from ract.memory.symbol_index import SymbolRow

if TYPE_CHECKING:
    from ract.memory.semantic_index import ChunkRow


MAX_TOKENS_PER_CHUNK: int = 500
"""Master spec §Chunk overflow threshold above which a symbol is split."""

CHUNK_KIND_FUNCTION_BODY: str = "function_body"
CHUNK_KIND_FUNCTION_SUBRANGE: str = "function_subrange"
CHUNK_KIND_CLASS_BODY: str = "class_body"
CHUNK_KIND_MODULE_BODY: str = "module_body"
CHUNK_KIND_DECLARATION: str = "declaration"

OVERSIZE_WARNING_KEY: str = "oversize"
"""Chunk locator prefix marking a sub-chunk that still exceeds the token cap."""


class OversizeChunkWarning(UserWarning):
    """Warned when a sub-chunk still exceeds :data:`MAX_TOKENS_PER_CHUNK`.

    The chunker emits the oversize sub-chunk anyway so the region is
    still reachable through the semantic index. Module_05's
    ``retrieve`` primitive is responsible for the SUMMARY fallback.
    """


def _kind_for_symbol(kind: str | None) -> str:
    """Map a module_02 symbol ``kind`` to the semantic-index chunk kind."""
    if kind in ("function", "method"):
        return CHUNK_KIND_FUNCTION_BODY
    if kind in ("class", "struct", "interface", "trait", "enum", "impl"):
        return CHUNK_KIND_CLASS_BODY
    if kind == "module":
        return CHUNK_KIND_MODULE_BODY
    return CHUNK_KIND_DECLARATION


def _slice_body(source: bytes, row: SymbolRow) -> str:
    """Return the source text for the symbol as a UTF-8 string.

    ``SymbolRow.start_line`` / ``end_line`` are 1-indexed inclusive
    per the module_02 parser convention. When either is None (a row
    that predates the module_02 parser fills), the chunker falls back
    to the whole file.
    """
    text = source.decode("utf-8", errors="replace")
    if row.start_line is None or row.end_line is None:
        return text
    lines = text.splitlines(keepends=True)
    start = max(0, row.start_line - 1)
    end = min(len(lines), row.end_line)
    return "".join(lines[start:end])


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _build_chunk(
    row: SymbolRow,
    body: str,
    chunk_kind: str,
    locator: str,
    signature: str | None,
    stamp: int,
) -> "ChunkRow":
    from ract.memory.semantic_index import ChunkRow  # avoid import cycle at load

    tokens = estimate_tokens(body)
    file_path = row.file_path
    content_hash = _content_hash(body)
    chunk_id = _chunk_id(file_path, row.name, chunk_kind, locator, content_hash)
    return ChunkRow(
        chunk_id=chunk_id,
        symbol_id=row.id if row.id is not None else -1,
        file_path=file_path,
        chunk_kind=chunk_kind,
        signature=signature if signature is not None else "",
        content_hash=content_hash,
        token_count=tokens,
        body=body,
        chunk_locator=locator,
        start_line=row.start_line,
        end_line=row.end_line,
        updated_at=stamp,
        vector=None,
    )


def _chunk_id(
    file_path: str, name: str, kind: str, locator: str, content_hash: str
) -> str:
    """Deterministic id: hash of (file, name, kind, locator, content_hash).

    Stable across re-runs so the same source produces the same chunk
    id; changing the body flips ``content_hash`` and therefore the id.
    The uniqueness constraint on the LanceDB store is written against
    ``chunk_id`` alone; updates via
    :meth:`~ract.memory.semantic_index.SemanticIndex.insert_or_update`
    replace by chunk_id.
    """
    hasher = hashlib.sha256()
    hasher.update(file_path.encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update(name.encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update(kind.encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update(locator.encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update(content_hash.encode("utf-8", errors="replace"))
    return hasher.hexdigest()


def _split_semantic_boundaries(body: str) -> list[str]:
    """Split ``body`` at logical boundaries: blank-line groups.

    A production sub-chunker would parse the AST for the body and
    split at for / while / if / try boundaries; that requires re-
    parsing the source with the per-language grammar, which is out of
    scope for module_04's chunker layer (module_02 owns tree-sitter
    parsing per language). This module ships a language-agnostic
    heuristic: split at runs of blank lines. The heuristic preserves
    the "each sub-chunk carries the parent function's signature"
    requirement because the caller (:func:`chunk_symbol`) prepends
    the signature after splitting.

    If ``body`` has no blank-line groups, returns ``[body]`` and the
    caller falls back to line-count splitting to hit the cap.
    """
    pieces: list[str] = []
    current: list[str] = []
    blank_streak = 0
    for line in body.splitlines(keepends=True):
        if line.strip() == "":
            blank_streak += 1
            current.append(line)
            continue
        if blank_streak >= 1 and current:
            joined = "".join(current)
            if joined.strip():
                pieces.append(joined)
            current = []
        blank_streak = 0
        current.append(line)
    if current:
        joined = "".join(current)
        if joined.strip():
            pieces.append(joined)
    if not pieces:
        pieces = [body]
    return pieces


def _split_by_line_count(body: str, max_lines_per_piece: int) -> list[str]:
    """Fallback splitter: fixed line-count windows.

    Used when :func:`_split_semantic_boundaries` returned a single
    piece that still exceeds the token cap (a giant if-block, a
    giant switch — the Second Pass Q3 case).
    """
    lines = body.splitlines(keepends=True)
    if not lines:
        return [body]
    if max_lines_per_piece < 1:
        max_lines_per_piece = 1
    pieces: list[str] = []
    for offset in range(0, len(lines), max_lines_per_piece):
        piece = "".join(lines[offset : offset + max_lines_per_piece])
        if piece.strip():
            pieces.append(piece)
    if not pieces:
        pieces = [body]
    return pieces


def _average_lines_per_token(body: str) -> float:
    """Return an approximate line-per-token ratio for ``body``."""
    lines = body.count("\n") or 1
    tokens = estimate_tokens(body) or 1
    return lines / tokens


def chunk_symbol(row: SymbolRow, source: str | bytes) -> list["ChunkRow"]:
    """Return the chunks for ``row``.

    Small symbols produce one chunk. Symbols whose ``token_count``
    exceeds :data:`MAX_TOKENS_PER_CHUNK` are split at logical
    boundaries (blank-line separated blocks); each sub-chunk carries
    the parent signature and a locator like ``"1/3"``.

    Reassembly is deterministic: sub-chunk locators are sorted
    ``"i/N"`` for ``i in 0..N-1``; concatenating the bodies in
    locator order reproduces the original body.

    If a single logical sub-chunk still exceeds
    :data:`MAX_TOKENS_PER_CHUNK`, it is emitted as-is with the
    locator prefixed by :data:`OVERSIZE_WARNING_KEY` and an
    :class:`OversizeChunkWarning` is warned. Callers that expect
    strict token-cap adherence (module_05 retrieve primitive) should
    consult the ``token_count`` on each chunk rather than assume the
    cap is honoured.

    Split levels: TWO. Level 1 is :func:`_split_semantic_boundaries`
    (blank-line-group split). Level 2 is :func:`_split_by_line_count`
    (line-count window). A pathological single-line 4000-token
    expression survives both levels intact and is emitted with the
    oversize marker (Second Pass Q3). Recursive re-splitting inside
    a single logical piece (a giant switch with six statements each
    over the cap) is Flagged gap 2; the module_05 SUMMARY chunker
    is the second-line owner of "still too big" bodies per master
    spec §Chunk overflow item 2.
    """
    if isinstance(source, bytes):
        source_bytes = source
    else:
        source_bytes = source.encode("utf-8")
    body = _slice_body(source_bytes, row)
    stamp = int(time.time())
    chunk_kind = _kind_for_symbol(row.kind)
    signature = row.signature
    tokens = estimate_tokens(body)
    if tokens <= MAX_TOKENS_PER_CHUNK:
        return [_build_chunk(row, body, chunk_kind, "0/1", signature, stamp)]
    # Split.
    logical_pieces = _split_semantic_boundaries(body)
    resolved_pieces: list[str] = []
    for piece in logical_pieces:
        piece_tokens = estimate_tokens(piece)
        if piece_tokens <= MAX_TOKENS_PER_CHUNK:
            resolved_pieces.append(piece)
            continue
        # Fall back to fixed-line splitting.
        ratio = _average_lines_per_token(piece)
        max_lines = max(1, int(MAX_TOKENS_PER_CHUNK * ratio))
        sub_pieces = _split_by_line_count(piece, max_lines)
        for sub in sub_pieces:
            if estimate_tokens(sub) > MAX_TOKENS_PER_CHUNK:
                warnings.warn(
                    (
                        f"chunk_symbol: emitting oversize sub-chunk for "
                        f"{row.file_path}:{row.name} ({estimate_tokens(sub)} "
                        f"tokens > cap {MAX_TOKENS_PER_CHUNK}); module_05's "
                        f"summarize_chunk fallback will apply."
                    ),
                    OversizeChunkWarning,
                    stacklevel=2,
                )
            resolved_pieces.append(sub)
    total = len(resolved_pieces)
    signature_prefix = f"{signature}\n" if signature else ""
    chunks: list[ChunkRow] = []
    for index, piece in enumerate(resolved_pieces):
        piece_tokens = estimate_tokens(piece)
        oversize = piece_tokens > MAX_TOKENS_PER_CHUNK
        locator = (
            f"{OVERSIZE_WARNING_KEY}:{index}/{total}"
            if oversize
            else f"{index}/{total}"
        )
        chunk_kind_actual = (
            CHUNK_KIND_FUNCTION_SUBRANGE
            if row.kind
            in (
                "function",
                "method",
            )
            else chunk_kind
        )
        body_with_signature = (
            f"{signature_prefix}{piece}" if signature_prefix else piece
        )
        chunks.append(
            _build_chunk(
                row=row,
                body=body_with_signature,
                chunk_kind=chunk_kind_actual,
                locator=locator,
                signature=signature,
                stamp=stamp,
            )
        )
    return chunks


__all__ = [
    "CHUNK_KIND_CLASS_BODY",
    "CHUNK_KIND_DECLARATION",
    "CHUNK_KIND_FUNCTION_BODY",
    "CHUNK_KIND_FUNCTION_SUBRANGE",
    "CHUNK_KIND_MODULE_BODY",
    "MAX_TOKENS_PER_CHUNK",
    "OVERSIZE_WARNING_KEY",
    "OversizeChunkWarning",
    "chunk_symbol",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
