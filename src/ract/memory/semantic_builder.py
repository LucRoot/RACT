"""Chunk-to-vector builder for the v0.5.0 semantic index.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Semantic
index. The builder walks every symbol in a
:class:`~ract.memory.symbol_index.SymbolIndex`, calls
:func:`~ract.memory.chunker.chunk_symbol` per symbol, embeds every
chunk via the store's :class:`~ract.memory.embedding.EmbeddingModel`
in batches, and inserts them into a
:class:`~ract.memory.semantic_index.SemanticIndex`.

Batches at :data:`DEFAULT_BATCH_SIZE` chunks per embed call so a
large repo (Lateral Chain branch B) does not stall on per-chunk
model calls. Progress reporting is behind a caller-supplied callback
so the shipped CLI (module_09) can plug into ``rich`` while tests
run silent.

Parent-symbol linkage (module_03 POST inbound constraint 2): the
builder walks every method-kind row after chunking and populates its
``parent_symbol_id`` against the class-kind row that contains the
method by line range. The linkage is a symbol-index write; the
semantic index does not carry it directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.chunker import chunk_symbol
from ract.memory.parser import parse_file
from ract.memory.semantic_index import (
    ChunkRow,
    SemanticIndex,
    rebuild_chunk_vectors,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow, _row_from_sqlite


_LOGGER = logging.getLogger(__name__)


DEFAULT_BATCH_SIZE: int = 32
"""Number of chunks the builder embeds per :meth:`EmbeddingModel.embed_batch` call."""


ProgressFn = Callable[[str, int, int], None]
"""Signature ``(stage, done, total)`` for the caller's progress hook."""


@dataclass
class BuildReport:
    """Result of :func:`initial_build`.

    - ``chunks_indexed`` — count of chunks inserted (across every
      symbol).
    - ``symbols_visited`` — count of symbols the walker visited.
    - ``embed_errors`` — count of chunks whose embedding raised;
      the chunk is skipped, the error is logged, and the build
      continues.
    - ``parent_symbols_linked`` — count of method rows whose
      ``parent_symbol_id`` the builder populated (module_03 POST
      inbound constraint 2).
    - ``elapsed_ms`` — wall-clock time in whole milliseconds.
    """

    chunks_indexed: int = 0
    symbols_visited: int = 0
    embed_errors: int = 0
    parent_symbols_linked: int = 0
    elapsed_ms: int = 0
    per_language: dict[str, int] = field(default_factory=dict)


@dataclass
class UpdateReport:
    """Result of :func:`update_symbol`.

    - ``deleted`` — chunks the update removed (stale chunks for the
      symbol).
    - ``inserted`` — chunks the update inserted (fresh chunks for
      the symbol).
    - ``elapsed_ms`` — wall-clock time in whole milliseconds.
    """

    deleted: int = 0
    inserted: int = 0
    elapsed_ms: int = 0


def _read_source_for(row: SymbolRow) -> bytes | None:
    """Return the raw source bytes for ``row.file_path`` or ``None``.

    ``None`` covers the case where the file has vanished between
    symbol-index build time and semantic-index build time (a race
    the operator can spot in the log). The builder skips the symbol.
    """
    path = Path(row.file_path)
    try:
        return path.read_bytes()
    except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        _LOGGER.warning(
            "semantic_builder: cannot read %s for symbol %s (%s); skipping",
            row.file_path,
            row.name,
            exc,
        )
        return None


def _batched(items: list[ChunkRow], size: int) -> list[list[ChunkRow]]:
    """Return ``items`` chunked into groups of at most ``size``."""
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _link_parent_symbols(symbols: SymbolIndex) -> int:
    """Populate ``parent_symbol_id`` for method-kind rows.

    Reads every ``class`` / ``struct`` / ``interface`` / ``impl`` row
    and finds method-kind rows whose start_line falls between the
    parent's start / end lines. Updates the method row's
    ``parent_symbol_id`` if it is currently NULL. Returns the number
    of rows updated.

    Module_03 POST inbound constraint 2: the schema column has been
    unused since module_02; module_04 is where the linkage lands.
    """
    conn = symbols.connection
    # Read all container-kind rows.
    containers = conn.execute(
        "SELECT id, file_path, start_line, end_line FROM symbols "
        "WHERE kind IN ('class', 'struct', 'interface', 'impl') "
        "AND start_line IS NOT NULL AND end_line IS NOT NULL"
    ).fetchall()
    updated = 0
    for container in containers:
        # Any method-kind row inside the container's line range in the
        # same file whose parent is not yet set.
        rows = conn.execute(
            "SELECT id FROM symbols WHERE kind = 'method' AND file_path = ? "
            "AND start_line IS NOT NULL AND start_line >= ? "
            "AND start_line <= ? AND parent_symbol_id IS NULL",
            (container["file_path"], container["start_line"], container["end_line"]),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE symbols SET parent_symbol_id = ? WHERE id = ?",
                (container["id"], row["id"]),
            )
            updated += 1
    if updated:
        conn.commit()
    return updated


def initial_build(
    root: Path | str,
    semantic: SemanticIndex,
    symbols: SymbolIndex,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: ProgressFn | None = None,
    link_parent_symbols: bool = True,
) -> BuildReport:
    """Chunk + embed + insert every symbol in ``symbols``.

    Reads through the symbol index's connection with a single cursor
    to avoid materialising every row for a 100k-line repo (Lateral
    Chain branch B). Embeds in batches of ``batch_size``; errors are
    logged and counted but do not stop the build.

    ``root`` is retained so a future scoped build can filter
    symbols by prefix; today the whole store is walked.
    """
    del root  # reserved for scoped-build hook
    started = time.perf_counter()
    report = BuildReport()
    cursor = symbols.connection.execute(
        "SELECT * FROM symbols ORDER BY file_path, start_line"
    )
    all_rows = [_row_from_sqlite(r) for r in cursor.fetchall()]
    total = len(all_rows)
    # Bucket by file so we read each file exactly once.
    by_file: dict[str, list[SymbolRow]] = {}
    for row in all_rows:
        by_file.setdefault(row.file_path, []).append(row)
    pending: list[ChunkRow] = []

    def _flush() -> None:
        nonlocal pending
        if not pending:
            return
        try:
            with_vectors = rebuild_chunk_vectors(pending, semantic.embedding)
        except Exception as exc:
            report.embed_errors += len(pending)
            _LOGGER.warning(
                "semantic_builder: embed batch of %d chunks failed (%s); dropped",
                len(pending),
                exc,
            )
            pending = []
            return
        semantic.insert_or_update_batch(with_vectors)
        report.chunks_indexed += len(with_vectors)
        pending = []

    visited = 0
    for file_path, file_rows in by_file.items():
        source = None
        for row in file_rows:
            if source is None:
                source_bytes = _read_source_for(row)
                if source_bytes is None:
                    visited += len(file_rows)
                    if progress is not None:
                        progress("chunk", visited, total)
                    break
                source = source_bytes
            chunks = chunk_symbol(row, source)
            for chunk in chunks:
                pending.append(chunk)
                if row.language is not None:
                    report.per_language[row.language] = (
                        report.per_language.get(row.language, 0) + 1
                    )
                if len(pending) >= batch_size:
                    _flush()
            visited += 1
            if progress is not None:
                progress("chunk", visited, total)
    _flush()
    report.symbols_visited = visited
    if link_parent_symbols:
        report.parent_symbols_linked = _link_parent_symbols(symbols)
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    _LOGGER.info(
        "semantic_builder.initial_build: chunks=%d symbols=%d errors=%d "
        "parents_linked=%d elapsed_ms=%d",
        report.chunks_indexed,
        report.symbols_visited,
        report.embed_errors,
        report.parent_symbols_linked,
        report.elapsed_ms,
    )
    return report


def update_symbol(
    symbol_id: int,
    semantic: SemanticIndex,
    symbols: SymbolIndex,
) -> UpdateReport:
    """Re-chunk + re-embed + re-insert every chunk for ``symbol_id``.

    Called from the module_09 watcher wiring on file save. Deletes
    stale chunks first via
    :meth:`~ract.memory.semantic_index.SemanticIndex.delete_by_symbol`
    so an update to a smaller body does not leave orphan chunks
    with stale content.
    """
    started = time.perf_counter()
    report = UpdateReport()
    cur = symbols.connection.execute(
        "SELECT * FROM symbols WHERE id = ?", (int(symbol_id),)
    )
    raw = cur.fetchone()
    if raw is None:
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report
    row = _row_from_sqlite(raw)
    source = _read_source_for(row)
    if source is None:
        # File vanished; remove any surviving chunks and return.
        report.deleted = semantic.delete_by_symbol(int(symbol_id))
        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report
    report.deleted = semantic.delete_by_symbol(int(symbol_id))
    chunks = chunk_symbol(row, source)
    if chunks:
        with_vectors = rebuild_chunk_vectors(chunks, semantic.embedding)
        semantic.insert_or_update_batch(with_vectors)
        report.inserted = len(with_vectors)
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return report


def build_from_files(
    files: list[Path | str],
    semantic: SemanticIndex,
    symbols: SymbolIndex,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BuildReport:
    """Build the semantic index from an explicit list of files.

    Scoped variant of :func:`initial_build` used by tests + the
    module_09 CLI's ``ract memory rebuild <path>`` verb. Every file
    is parsed through :func:`~ract.memory.parser.parse_file`, its
    symbols inserted into the store via ``replace_file``, then its
    chunks embedded + inserted.
    """
    started = time.perf_counter()
    report = BuildReport()
    pending: list[ChunkRow] = []

    def _flush() -> None:
        nonlocal pending
        if not pending:
            return
        try:
            with_vectors = rebuild_chunk_vectors(pending, semantic.embedding)
        except Exception as exc:
            report.embed_errors += len(pending)
            _LOGGER.warning(
                "semantic_builder.build_from_files: embed batch of %d chunks "
                "failed (%s); dropped",
                len(pending),
                exc,
            )
            pending = []
            return
        semantic.insert_or_update_batch(with_vectors)
        report.chunks_indexed += len(with_vectors)
        pending = []

    for raw_path in files:
        path = Path(raw_path).resolve()
        try:
            parsed_rows = parse_file(path)
        except Exception as exc:
            _LOGGER.warning(
                "semantic_builder.build_from_files: parse_file failed for %s (%s)",
                path,
                exc,
            )
            continue
        # Normalise file_path to the resolved absolute path.
        parsed_rows = [row._replace(file_path=str(path)) for row in parsed_rows]
        assigned_ids = symbols.replace_file(str(path), parsed_rows)
        for row_id, row in zip(assigned_ids, parsed_rows, strict=True):
            row_with_id = row._replace(id=row_id)
            source = _read_source_for(row_with_id)
            if source is None:
                continue
            chunks = chunk_symbol(row_with_id, source)
            for chunk in chunks:
                pending.append(chunk)
                if row.language is not None:
                    report.per_language[row.language] = (
                        report.per_language.get(row.language, 0) + 1
                    )
                if len(pending) >= batch_size:
                    _flush()
            report.symbols_visited += 1
    _flush()
    report.parent_symbols_linked = _link_parent_symbols(symbols)
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return report


__all__ = [
    "BuildReport",
    "DEFAULT_BATCH_SIZE",
    "ProgressFn",
    "UpdateReport",
    "build_from_files",
    "initial_build",
    "update_symbol",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
