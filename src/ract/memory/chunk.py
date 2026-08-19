"""Chunk value type and format converter for the retrieve primitive.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
retrieve primitive. The retrieve output is a
:class:`~ract.memory.retrieve.RetrievalBundle` whose members are
:class:`Chunk` instances (this module's type). A :class:`Chunk` is a
retrieval-oriented view over one
:class:`~ract.memory.semantic_index.ChunkRow` OR one
:class:`~ract.memory.symbol_index.SymbolRow` — either surface can
seed a chunk since exact-name matches never touch the semantic store.

:func:`format_chunk` is a pure converter across four formats:

- ``FULL`` — full body (as stored). Default cascade level 1 output.
- ``BODY_ONLY`` — body without any prepended signature.
- ``SIGNATURE`` — signature only; empty body. Cascade downgrade output.
- ``SUMMARY`` — provider-generated one-line summary. Placeholder here;
  a real provider integration lands in a later module. When no summary
  is available the returned chunk carries ``body = "summary unavailable"``
  and ``summary_pending = True`` (Flagged gap for module_06 wiring).

:func:`chunk_from_symbol` composes a :class:`Chunk` from a
:class:`~ract.memory.symbol_index.SymbolRow` + the source bytes.
Used by cascade paths that fire against the symbol index directly
without going through the semantic store's :class:`ChunkRow`.

Oversize-marker handshake (module_04 POST inbound constraint 2):
:func:`chunk_from_chunk_row` preserves the ``oversize:`` locator
prefix from :mod:`ract.memory.chunker`. The retrieve primitive
consults :attr:`Chunk.oversize` and either surfaces the chunk with
a truncation note (bundle-level ``truncation_notes`` list) or
excludes it with a ``chunk too large`` marker. Silent strip is
refused.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.parser import estimate_tokens
from ract.memory.symbol_index import SymbolRow


class ChunkFormat(enum.Enum):
    """Rendering format for a retrieved chunk.

    Master spec §The retrieve primitive lists four values. FULL is the
    default (cascade level 1). BODY_ONLY drops the prepended signature.
    SIGNATURE emits the declaration only. SUMMARY delegates to a
    provider; the placeholder returns ``"summary unavailable"`` until
    the module_06 provider wiring lands.
    """

    FULL = "full"
    BODY_ONLY = "body"
    SIGNATURE = "sig"
    SUMMARY = "summary"


@dataclass(frozen=True)
class Chunk:
    """A retrieval-oriented view over one indexed unit.

    Fields:

    - ``chunk_id`` — deterministic id for the source unit. Reuses the
      module_04 :class:`~ract.memory.semantic_index.ChunkRow.chunk_id`
      when the seed was a ChunkRow; otherwise a hash of
      ``(file_path, symbol_name, kind, content_hash)``.
    - ``symbol_id`` — foreign key to
      :attr:`~ract.memory.symbol_index.SymbolRow.id`. ``-1`` when the
      seed had no id (test fixtures that hand-build a Chunk).
    - ``symbol_name`` — the symbol's name; carried at chunk level so
      the query trace can name dropped symbols without a second lookup.
    - ``file_path`` — absolute source path of the seed.
    - ``language`` — language tag; matches
      :attr:`~ract.memory.symbol_index.SymbolRow.language`. ``None`` on
      seeds that predate the language column.
    - ``kind`` — chunk kind (``function_body`` / ``class_body`` /
      ``declaration`` / ``function_subrange`` / ``module_body``) or
      the symbol kind for direct-from-symbol chunks.
    - ``signature`` — declaration text (empty string when unavailable).
    - ``body`` — chunk text as rendered under the current
      :class:`ChunkFormat`.
    - ``content_hash`` — SHA-256 of the seed's canonical body. Retrieve
      dedup runs on ``content_hash`` (module_04 POST inbound constraint
      3): two ChunkRow rows with identical hashes collapse to one in
      the bundle even when their ``chunk_id`` values differ.
    - ``token_count`` — token cost of ``body`` under the shipped
      whitespace estimator. Callers using a provider-native tokenizer
      compute their own count and reseat.
    - ``oversize`` — ``True`` when the seed's chunk locator carried the
      module_04 ``oversize:`` marker (Second Pass Q3 handshake).
    - ``chunk_locator`` — position identifier (``"0/1"`` for single-
      chunk symbols; ``"i/N"`` for sub-chunks; ``"oversize:i/N"`` for
      oversize sub-chunks).
    - ``start_line`` / ``end_line`` — 1-indexed inclusive source lines.
    - ``summary_pending`` — ``True`` when a SUMMARY-format render was
      requested but no provider was supplied; the placeholder body is
      ``"summary unavailable"`` and callers should surface this state.
    - ``metadata`` — free-form key/value map for downstream consumers;
      the retrieve primitive attaches ``source_index`` (``symbol`` /
      ``graph`` / ``semantic`` / ``symbol_from_graph``) and other
      provenance fields (module_04 constraint E: query trace names the
      source index per hit).
    """

    chunk_id: str
    symbol_id: int
    symbol_name: str
    file_path: str
    language: str | None
    kind: str
    signature: str
    body: str
    content_hash: str
    token_count: int
    oversize: bool
    chunk_locator: str
    start_line: int | None
    end_line: int | None
    summary_pending: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _slice_symbol_body(source: bytes, row: SymbolRow) -> str:
    """Return the source text for ``row`` as a UTF-8 string.

    Mirrors :func:`ract.memory.chunker._slice_body` — kept local to
    avoid importing a private helper across modules.
    """
    text = source.decode("utf-8", errors="replace")
    if row.start_line is None or row.end_line is None:
        return text
    lines = text.splitlines(keepends=True)
    start = max(0, row.start_line - 1)
    end = min(len(lines), row.end_line)
    return "".join(lines[start:end])


def chunk_from_symbol(row: SymbolRow, source: str | bytes) -> Chunk:
    """Build a :class:`Chunk` for ``row`` by slicing ``source``.

    Used by cascade paths that fire against the symbol index directly
    (Level 1 exact-name matches when the semantic store has no chunk
    for the symbol yet, or the LSP-fallback path where the graph seed
    resolves to a symbol without a chunk).

    Returns a FULL-format chunk; the caller runs :func:`format_chunk`
    to downgrade to SIGNATURE for cascade levels 2-4.
    """
    if isinstance(source, bytes):
        source_bytes = source
    else:
        source_bytes = source.encode("utf-8")
    body = _slice_symbol_body(source_bytes, row)
    signature = row.signature or ""
    content_hash = row.content_hash or _content_hash(body)
    hasher = hashlib.sha256()
    hasher.update(row.file_path.encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update(row.name.encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update((row.kind or "").encode("utf-8", errors="replace"))
    hasher.update(b"\x00")
    hasher.update(content_hash.encode("utf-8", errors="replace"))
    chunk_id = hasher.hexdigest()
    return Chunk(
        chunk_id=chunk_id,
        symbol_id=row.id if row.id is not None else -1,
        symbol_name=row.name,
        file_path=row.file_path,
        language=row.language,
        kind=row.kind,
        signature=signature,
        body=body,
        content_hash=content_hash,
        token_count=row.token_count
        if row.token_count is not None
        else estimate_tokens(body),
        oversize=False,
        chunk_locator="0/1",
        start_line=row.start_line,
        end_line=row.end_line,
        metadata={"source_index": "symbol"},
    )


def chunk_from_chunk_row(chunk_row: Any, source_index_label: str = "semantic") -> Chunk:
    """Build a :class:`Chunk` from a module_04
    :class:`~ract.memory.semantic_index.ChunkRow`.

    Preserves the oversize marker (module_04 POST inbound constraint 2):
    the returned :attr:`Chunk.oversize` mirrors whether the ChunkRow's
    ``chunk_locator`` starts with ``"oversize:"``. The retrieve
    primitive reads this flag and either surfaces the chunk with a
    truncation note or excludes it with a ``chunk too large`` marker.
    """
    locator = chunk_row.chunk_locator
    oversize = locator.startswith("oversize:")
    return Chunk(
        chunk_id=chunk_row.chunk_id,
        symbol_id=chunk_row.symbol_id,
        symbol_name=_extract_symbol_name(chunk_row),
        file_path=chunk_row.file_path,
        language=None,
        kind=chunk_row.chunk_kind,
        signature=chunk_row.signature or "",
        body=chunk_row.body,
        content_hash=chunk_row.content_hash,
        token_count=chunk_row.token_count,
        oversize=oversize,
        chunk_locator=locator,
        start_line=chunk_row.start_line,
        end_line=chunk_row.end_line,
        metadata={"source_index": source_index_label},
    )


def _extract_symbol_name(chunk_row: Any) -> str:
    """Best-effort symbol name extraction for a
    :class:`~ract.memory.semantic_index.ChunkRow`.

    The ChunkRow type does not carry the symbol name directly; the
    signature does, and callers that need a stable identifier can
    resolve it via the symbol index. This helper returns the first
    whitespace token of the signature, falling back to
    ``"symbol_{symbol_id}"`` when the signature is empty.
    """
    if chunk_row.signature:
        first = chunk_row.signature.strip().split()
        if first:
            return first[-1].split("(")[0].strip(":=") or first[-1]
    return f"symbol_{chunk_row.symbol_id}"


def format_chunk(
    chunk: Chunk,
    format: ChunkFormat,
    provider: Any | None = None,
) -> Chunk:
    """Return a new :class:`Chunk` rendered under ``format``.

    Pure for FULL / BODY_ONLY / SIGNATURE. Delegates to
    ``provider.summarize(chunk)`` when ``format is SUMMARY`` and a
    provider is supplied; otherwise returns a chunk whose body is
    ``"summary unavailable"`` and whose :attr:`Chunk.summary_pending`
    is ``True``. A real provider wiring lands in module_06.

    Token-count is recomputed against the rendered body via the
    shipped :func:`~ract.memory.parser.estimate_tokens` so a caller
    who downgrades a FULL chunk to SIGNATURE gets the reduced count
    for free.
    """
    if format is ChunkFormat.FULL:
        new_body = chunk.body
        pending = False
    elif format is ChunkFormat.BODY_ONLY:
        new_body = _strip_signature(chunk)
        pending = False
    elif format is ChunkFormat.SIGNATURE:
        new_body = chunk.signature
        pending = False
    elif format is ChunkFormat.SUMMARY:
        if provider is None or not hasattr(provider, "summarize"):
            new_body = "summary unavailable"
            pending = True
        else:
            summarized = provider.summarize(chunk)
            new_body = str(summarized)
            pending = False
    else:
        raise ValueError(f"format_chunk: unknown format {format!r}")
    return Chunk(
        chunk_id=chunk.chunk_id,
        symbol_id=chunk.symbol_id,
        symbol_name=chunk.symbol_name,
        file_path=chunk.file_path,
        language=chunk.language,
        kind=chunk.kind,
        signature=chunk.signature,
        body=new_body,
        content_hash=chunk.content_hash,
        token_count=estimate_tokens(new_body),
        oversize=chunk.oversize,
        chunk_locator=chunk.chunk_locator,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        summary_pending=pending,
        metadata=dict(chunk.metadata),
    )


def _strip_signature(chunk: Chunk) -> str:
    """Return :attr:`Chunk.body` with the prepended signature removed.

    The module_04 chunker's sub-chunk path prepends the parent
    signature plus a newline before the piece body. BODY_ONLY strips
    exactly one such prefix when present; otherwise returns the body
    unchanged.
    """
    if not chunk.signature:
        return chunk.body
    prefix = f"{chunk.signature}\n"
    if chunk.body.startswith(prefix):
        return chunk.body[len(prefix) :]
    return chunk.body


__all__ = [
    "Chunk",
    "ChunkFormat",
    "chunk_from_chunk_row",
    "chunk_from_symbol",
    "format_chunk",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
