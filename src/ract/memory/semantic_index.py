"""LanceDB-backed semantic index for the memory-discipline pipeline.

Ships the :class:`SemanticIndex` store + :class:`ChunkRow` value
type + query API (``search`` / ``search_by_symbol`` /
``search_with_budget``) + write API
(``insert_or_update`` / ``delete_by_symbol``).

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` section
"The three indexes / Semantic index". Rationale: ADR-0034.

Chunk identity joins on
:attr:`~ract.memory.symbol_index.SymbolRow.content_hash` and the
module_02 ``symbols.id`` foreign key. The store does not create a
parallel symbol id space (module_02 POST inbound constraint 2).

The store lives at ``.ract/index/semantic/`` in a real repo; tests
open a temp path. A ``metadata.json`` alongside the LanceDB
directory records the ``embedding_model_name`` + ``embedding_dim``
that produced the stored vectors. A mismatch on re-open raises
:class:`EmbeddingModelMismatchError` with a "rebuild required"
message (Lateral Chain branch E). A metadata file that goes missing
while the ``chunks`` table remains populated raises
:class:`SemanticStoreCorruptError` (Second Pass Q4).

Query API accepts an optional
:class:`~ract.memory.budget.BudgetAccountant` on
:meth:`SemanticIndex.search_with_budget` so callers seat the token
cost of the returned chunks against the same accountant that gates
the downstream model call.

Graph enrichment (module_03 POST inbound constraint 1) is
implemented by :meth:`SemanticIndex.enrich_with_graph`, which
filters ``neighborhood_source='lsp'`` by default; callers who want
symbol-only fallback edges to appear in a semantic-quality read
must opt in via ``include_symbol_only=True``.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Iterable, Literal, NamedTuple

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetAccountant, BudgetSection
from ract.memory.cpu_fallback import LanceDbProbeResult, probe_lancedb
from ract.memory.embedding import (
    DEFAULT_MODEL_NAME,
    EmbeddingModel,
    load_embedding,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


_LOGGER = logging.getLogger(__name__)


METADATA_FILE_NAME: str = "metadata.json"
CHUNKS_TABLE_NAME: str = "chunks"
CURRENT_SCHEMA_VERSION: str = "v1"
DEFAULT_TOP_K: int = 10


CHUNK_KINDS: frozenset[str] = frozenset(
    {
        "function_body",
        "function_subrange",
        "class_body",
        "module_body",
        "declaration",
    }
)


class SemanticIndexError(RuntimeError):
    """Raised on caller-side misuse of the semantic index API."""


class LanceDbUnavailableError(SemanticIndexError):
    """Raised when :func:`~ract.memory.cpu_fallback.probe_lancedb` reports
    LanceDB as unavailable and the caller opened a :class:`SemanticIndex`.
    """


class EmbeddingModelMismatchError(SemanticIndexError):
    """Raised when the stored metadata disagrees with the supplied embedder.

    Same store must never be re-used with a different embedding
    model. The recovery is to delete the store and re-run
    :func:`~ract.memory.semantic_builder.initial_build` under the new
    embedder (Lateral Chain branch E).
    """


class SemanticStoreCorruptError(SemanticIndexError):
    """Raised when the ``chunks`` table exists but ``metadata.json`` is missing.

    The store cannot know the vector dimension of the stored rows
    without the metadata file; a query issued against the store
    would silently mix vector spaces. Second Pass Q4: detect
    corruption explicitly rather than proceed to run.
    """


class ChunkRow(NamedTuple):
    """One row in the LanceDB ``chunks`` table.

    Fields:

    - ``chunk_id`` — deterministic hash of
      (file_path, symbol_name, chunk_kind, chunk_locator, content_hash).
      Primary key for update-in-place.
    - ``symbol_id`` — foreign key to module_02
      :attr:`~ract.memory.symbol_index.SymbolRow.id`. ``-1`` for
      chunks whose parent symbol has not yet been persisted (tests
      that construct chunks by hand).
    - ``file_path`` — absolute source path of the parent symbol.
    - ``chunk_kind`` — one of :data:`CHUNK_KINDS`. Filters queries
      that only care about function bodies vs class bodies.
    - ``signature`` — the parent symbol's signature; sub-chunks
      carry it in ``body`` too so the model sees the context.
    - ``content_hash`` — SHA-256 of the chunk body. The module_02
      symbol store's ``content_hash`` is on the whole symbol; this
      one is on the chunk body which includes the prepended
      signature for sub-chunks.
    - ``token_count`` — whitespace-token estimate from
      :func:`~ract.memory.parser.estimate_tokens`.
    - ``body`` — the chunk text as stored. Callers who want just
      the signature read :attr:`signature` instead.
    - ``chunk_locator`` — position identifier for sub-chunks:
      ``"0/1"`` for single-chunk symbols; ``"i/N"`` for the ``i``-th
      of ``N`` sub-chunks; ``"oversize:i/N"`` for a sub-chunk that
      still exceeds the token cap (see
      :class:`~ract.memory.chunker.OversizeChunkWarning`).
    - ``start_line`` / ``end_line`` — 1-indexed inclusive source
      lines for the chunk region (or the parent symbol when the
      chunk covers the whole symbol).
    - ``updated_at`` — unix timestamp of the chunk build; used for
      diagnostic "when did this land" queries.
    - ``vector`` — the embedding. ``None`` on chunks the builder
      has not yet embedded; a live search never reads ``None``
      vectors because the builder embeds before insert.
    - ``sub_chunk_method`` — module_05 SP amendment (cross-family SP reviewer
      Q10 item 1). Names the splitter that produced this row when it
      is a sub-chunk: one of :data:`~ract.memory.chunker.SUB_CHUNK_METHOD_AST`
      / :data:`~ract.memory.chunker.SUB_CHUNK_METHOD_BLANK_LINE`, or
      ``None`` for single-chunk symbols (no split ran) and for rows
      re-hydrated from the LanceDB store (persistence deferred to
      v0.6 with the schema bump). Downstream may branch on the
      splitter that fired without re-reading the chunker source.
    - ``language`` — module_05 SP amendment (cross-family SP reviewer Q10 item
      5). Threaded from :attr:`~ract.memory.symbol_index.SymbolRow.language`
      at chunk-build time so downstream SUMMARY formatting selects
      the correct per-language control-flow keyword catalog on rows
      that pre-date the store's language column. ``None`` for rows
      re-hydrated from LanceDB (persistence deferred to v0.6);
      callers derive language from :attr:`file_path` suffix in that
      case (see :func:`ract.memory.chunk._infer_language_from_path`).
    """

    chunk_id: str
    symbol_id: int
    file_path: str
    chunk_kind: str
    signature: str
    content_hash: str
    token_count: int
    body: str
    chunk_locator: str
    start_line: int | None
    end_line: int | None
    updated_at: int
    vector: list[float] | None
    sub_chunk_method: str | None = None
    language: str | None = None


class SemanticIndex:
    """LanceDB-backed semantic index for AST chunks.

    Opens (creating if missing) a LanceDB store at ``store_path``.
    The store carries a ``metadata.json`` file alongside the
    LanceDB directory recording the embedding model name + vector
    dim; a re-open under a different embedder raises
    :class:`EmbeddingModelMismatchError`.

    Use as a context manager
    (``with SemanticIndex(path, symbols, embedding) as sem: ...``)
    or manage manually with :meth:`close`.
    """

    def __init__(
        self,
        store_path: Path | str,
        symbol_index: SymbolIndex,
        embedding: EmbeddingModel | None = None,
    ) -> None:
        self._probe: LanceDbProbeResult = probe_lancedb()
        if not self._probe.available:
            raise LanceDbUnavailableError(
                "SemanticIndex requires lancedb; probe returned unavailable: "
                f"{self._probe.error_message}"
            )
        # Lazy import mirrors the module_03 multilspy pattern so
        # test paths that never open a store do not pay the
        # LanceDB import cost.
        import lancedb  # type: ignore[import-not-found]
        import pyarrow as pa  # type: ignore[import-not-found]

        self._pa = pa
        self._store_path: Path = Path(store_path).resolve()
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._symbol_index: SymbolIndex = symbol_index
        self._embedding: EmbeddingModel = embedding or load_embedding(
            DEFAULT_MODEL_NAME
        )
        # Metadata read-or-write. If the store existed already and the
        # metadata disagrees with the supplied embedder we refuse.
        self._metadata_path: Path = self._store_path / METADATA_FILE_NAME
        self._db: Any = lancedb.connect(str(self._store_path))
        self._table_name: str = CHUNKS_TABLE_NAME
        # ``list_tables`` on newer LanceDB returns a ListTablesResponse
        # object with a ``.tables`` attribute; older builds return a plain
        # list; older still expose ``table_names()``. Normalise here so the
        # rest of __init__ works against a plain iterable regardless.
        existing_tables = self._resolve_table_names(self._db)
        table_present = self._table_name in existing_tables
        metadata_present = self._metadata_path.is_file()
        if table_present and not metadata_present:
            raise SemanticStoreCorruptError(
                f"Semantic store at {self._store_path!s} has a {self._table_name!r} "
                f"table but no {METADATA_FILE_NAME!s}; refusing to open. Delete "
                f"the store directory and rebuild via semantic_builder.initial_build."
            )
        if metadata_present:
            stored = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            if stored.get("embedding_model_name") != self._embedding.name:
                raise EmbeddingModelMismatchError(
                    f"Semantic store at {self._store_path!s} was built with "
                    f"embedding {stored.get('embedding_model_name')!r} (dim "
                    f"{stored.get('embedding_dim')}); caller supplied "
                    f"{self._embedding.name!r} (dim {self._embedding.dim}). "
                    f"Delete the store and rebuild, or reopen under the "
                    f"original embedder."
                )
            if int(stored.get("embedding_dim", 0)) != self._embedding.dim:
                raise EmbeddingModelMismatchError(
                    f"Semantic store metadata records dim "
                    f"{stored.get('embedding_dim')} but embedder "
                    f"{self._embedding.name!r} reports dim {self._embedding.dim}"
                )
        else:
            self._write_metadata()
        # Ensure the table exists — an empty create at open time keeps
        # the schema stable so first-run searches do not have to check
        # existence before every query.
        if not table_present:
            self._create_empty_table()
        _LOGGER.info(
            "SemanticIndex open at %s (backend=%s, embedder=%s dim=%d)",
            self._store_path,
            self._probe.backend,
            self._embedding.name,
            self._embedding.dim,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "SemanticIndex":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release the LanceDB connection.

        LanceDB's Python binding does not expose an explicit close
        for the connection object; dropping the reference triggers
        the native close on garbage collection. This method exists
        so callers can use ``with`` blocks + explicit teardown for
        parity with :class:`~ract.memory.symbol_index.SymbolIndex`
        and :class:`~ract.memory.graph_index.GraphIndex`.
        """
        self._db = None

    @property
    def store_path(self) -> Path:
        return self._store_path

    @property
    def embedding(self) -> EmbeddingModel:
        return self._embedding

    @property
    def symbol_index(self) -> SymbolIndex:
        return self._symbol_index

    @property
    def lance_probe(self) -> LanceDbProbeResult:
        return self._probe

    @property
    def dim(self) -> int:
        return self._embedding.dim

    def count(self) -> int:
        """Return the number of chunks in the store."""
        table = self._db.open_table(self._table_name)
        return int(table.count_rows())

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def _arrow_schema(self) -> Any:
        pa = self._pa
        return pa.schema(
            [
                pa.field("chunk_id", pa.string()),
                pa.field("symbol_id", pa.int64()),
                pa.field("file_path", pa.string()),
                pa.field("chunk_kind", pa.string()),
                pa.field("signature", pa.string()),
                pa.field("content_hash", pa.string()),
                pa.field("token_count", pa.int64()),
                pa.field("body", pa.string()),
                pa.field("chunk_locator", pa.string()),
                pa.field("start_line", pa.int64()),
                pa.field("end_line", pa.int64()),
                pa.field("updated_at", pa.int64()),
                pa.field("vector", pa.list_(pa.float32(), self._embedding.dim)),
            ]
        )

    def _create_empty_table(self) -> None:
        self._db.create_table(self._table_name, schema=self._arrow_schema())

    @staticmethod
    def _resolve_table_names(db: Any) -> list[str]:
        """Return the list of table names for the connection ``db``.

        LanceDB shipped three call shapes in as many years:

        - Legacy: ``db.table_names()`` returns ``list[str]``.
        - Middle: ``db.list_tables()`` returns ``list[str]``.
        - Current: ``db.list_tables()`` returns a
          ``ListTablesResponse`` with a ``.tables`` attribute.

        This helper collapses all three onto a plain ``list[str]``.
        """
        if hasattr(db, "list_tables"):
            result = db.list_tables()
        else:
            result = db.table_names()
        if hasattr(result, "tables"):
            return list(result.tables)
        return list(result)

    def _write_metadata(self) -> None:
        payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "embedding_model_name": self._embedding.name,
            "embedding_dim": self._embedding.dim,
            "created_at": int(time.time()),
        }
        self._metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def read_metadata(self) -> dict[str, Any]:
        """Return the parsed metadata dict.

        Convenience for tests + diagnostics. The stored file is the
        source of truth; this helper just re-reads and parses it.
        """
        if not self._metadata_path.is_file():
            return {}
        return json.loads(self._metadata_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_or_update(self, chunk: ChunkRow) -> None:
        """Insert ``chunk`` (or replace an existing row on ``chunk_id``).

        The chunk's ``vector`` must be non-None and match the store's
        embedding dim. LanceDB's ``add`` on a table with a matching
        ``chunk_id`` would produce a duplicate row; we ``delete`` the
        existing row by chunk_id first for an update-in-place shape.
        """
        self._validate_chunk(chunk)
        table = self._db.open_table(self._table_name)
        # Predicate-safe SQL: chunk_id is a hex string (no quoting risk).
        table.delete(f"chunk_id = '{chunk.chunk_id}'")
        table.add([self._chunk_to_row(chunk)])

    def insert_or_update_batch(self, chunks: list[ChunkRow]) -> None:
        """Batch variant of :meth:`insert_or_update`.

        Deletes matching chunk_ids then adds every chunk in one
        LanceDB write. Callers building at scale (module_04
        :func:`~ract.memory.semantic_builder.initial_build`) should
        prefer this path so each chunk does not pay a fresh write
        roundtrip.
        """
        if not chunks:
            return
        for chunk in chunks:
            self._validate_chunk(chunk)
        table = self._db.open_table(self._table_name)
        chunk_ids = ",".join(f"'{c.chunk_id}'" for c in chunks)
        table.delete(f"chunk_id IN ({chunk_ids})")
        table.add([self._chunk_to_row(chunk) for chunk in chunks])

    def delete_by_symbol(self, symbol_id: int) -> int:
        """Delete every chunk for ``symbol_id``. Returns the number deleted.

        Called from the module_09 watcher-driven update path when a
        symbol is re-parsed: delete old chunks, chunk + embed +
        insert fresh ones.
        """
        table = self._db.open_table(self._table_name)
        before = int(table.count_rows())
        table.delete(f"symbol_id = {int(symbol_id)}")
        after = int(table.count_rows())
        return before - after

    def delete_by_file(self, file_path: str) -> int:
        """Delete every chunk anchored at ``file_path``.

        Used when a source file is removed entirely; the watcher
        emits ``on_deleted`` and the update path cascades through
        this helper.
        """
        table = self._db.open_table(self._table_name)
        before = int(table.count_rows())
        escaped = file_path.replace("'", "''")
        table.delete(f"file_path = '{escaped}'")
        after = int(table.count_rows())
        return before - after

    def _validate_chunk(self, chunk: ChunkRow) -> None:
        if chunk.vector is None:
            raise SemanticIndexError(
                f"insert_or_update: chunk {chunk.chunk_id!r} has no vector; "
                f"embed via EmbeddingModel.embed_batch before insert."
            )
        if len(chunk.vector) != self._embedding.dim:
            raise SemanticIndexError(
                f"insert_or_update: chunk {chunk.chunk_id!r} vector dim "
                f"{len(chunk.vector)} does not match store dim "
                f"{self._embedding.dim}"
            )
        if chunk.chunk_kind not in CHUNK_KINDS:
            raise SemanticIndexError(
                f"insert_or_update: chunk_kind {chunk.chunk_kind!r} not in "
                f"CHUNK_KINDS {sorted(CHUNK_KINDS)!r}"
            )

    def _chunk_to_row(self, chunk: ChunkRow) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "symbol_id": int(chunk.symbol_id),
            "file_path": chunk.file_path,
            "chunk_kind": chunk.chunk_kind,
            "signature": chunk.signature,
            "content_hash": chunk.content_hash,
            "token_count": int(chunk.token_count),
            "body": chunk.body,
            "chunk_locator": chunk.chunk_locator,
            "start_line": chunk.start_line if chunk.start_line is not None else -1,
            "end_line": chunk.end_line if chunk.end_line is not None else -1,
            "updated_at": int(chunk.updated_at),
            "vector": [float(v) for v in (chunk.vector or [])],
        }

    def _row_to_chunk(self, row: dict[str, Any]) -> ChunkRow:
        start_line = row.get("start_line")
        end_line = row.get("end_line")
        return ChunkRow(
            chunk_id=str(row["chunk_id"]),
            symbol_id=int(row["symbol_id"]),
            file_path=str(row["file_path"]),
            chunk_kind=str(row["chunk_kind"]),
            signature=str(row.get("signature", "")),
            content_hash=str(row["content_hash"]),
            token_count=int(row.get("token_count", 0)),
            body=str(row.get("body", "")),
            chunk_locator=str(row.get("chunk_locator", "0/1")),
            start_line=(
                int(start_line)
                if start_line is not None and int(start_line) >= 0
                else None
            ),
            end_line=(
                int(end_line) if end_line is not None and int(end_line) >= 0 else None
            ),
            updated_at=int(row.get("updated_at", 0)),
            vector=[float(v) for v in row["vector"]]
            if row.get("vector") is not None
            else None,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _apply_filter(self, query_builder: Any, filter: dict[str, Any] | None) -> Any:
        """Compose a LanceDB ``where`` clause from a dict filter.

        Only equality on scalar columns is supported; the value must
        be a string or int. Callers wanting complex filters build the
        SQL string themselves and pass it to LanceDB directly through
        the returned builder (LanceDB exposes ``where`` on the search
        builder object).
        """
        if not filter:
            return query_builder
        clauses: list[str] = []
        for key, value in filter.items():
            if key not in {
                "symbol_id",
                "file_path",
                "chunk_kind",
                "chunk_locator",
                "content_hash",
            }:
                raise SemanticIndexError(
                    f"search: filter key {key!r} not in the supported set"
                )
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                clauses.append(f"{key} = {value}")
            else:
                escaped = str(value).replace("'", "''")
                clauses.append(f"{key} = '{escaped}'")
        return query_builder.where(" AND ".join(clauses))

    def search(
        self,
        query_text: str,
        top_k: int = DEFAULT_TOP_K,
        filter: dict[str, Any] | None = None,
    ) -> list[ChunkRow]:
        """Return the ``top_k`` most similar chunks to ``query_text``.

        Embeds the query with the store's embedder, runs a vector
        search over LanceDB, materialises each hit as a
        :class:`ChunkRow`. Filter dict supports equality on
        ``symbol_id`` / ``file_path`` / ``chunk_kind`` /
        ``chunk_locator`` / ``content_hash`` (SQL passthrough).
        """
        if top_k <= 0:
            return []
        vector = self._embedding.embed(query_text)
        table = self._db.open_table(self._table_name)
        builder = table.search(vector).limit(top_k)
        builder = self._apply_filter(builder, filter)
        rows = builder.to_list()
        return [self._row_to_chunk(row) for row in rows]

    def search_by_symbol(
        self, symbol_id: int, top_k: int = DEFAULT_TOP_K
    ) -> list[ChunkRow]:
        """Return chunks similar to the seed chunk(s) for ``symbol_id``.

        Reads every chunk with the given ``symbol_id`` (a large
        symbol may have several sub-chunks), averages their vectors,
        and runs the resulting mean vector against the store. Skips
        the symbol's own chunks in the returned list so the caller
        gets neighbours rather than the seed itself.
        """
        if top_k <= 0:
            return []
        table = self._db.open_table(self._table_name)
        # LanceDB's SQL scan for the seed rows.
        seed_rows = table.search().where(f"symbol_id = {int(symbol_id)}").to_list()
        if not seed_rows:
            return []
        seed_vectors: list[list[float]] = []
        for row in seed_rows:
            vec = row.get("vector")
            if vec is None:
                continue
            seed_vectors.append([float(v) for v in vec])
        if not seed_vectors:
            return []
        dim = len(seed_vectors[0])
        mean = [0.0] * dim
        for vec in seed_vectors:
            for i, v in enumerate(vec):
                mean[i] += v
        mean = [v / len(seed_vectors) for v in mean]
        # Normalise so search magnitude does not skew.
        norm = math.sqrt(sum(v * v for v in mean))
        if norm > 0:
            mean = [v / norm for v in mean]
        builder = table.search(mean).limit(top_k + len(seed_rows))
        rows = builder.to_list()
        results: list[ChunkRow] = []
        for row in rows:
            if int(row.get("symbol_id", -1)) == int(symbol_id):
                continue
            results.append(self._row_to_chunk(row))
            if len(results) >= top_k:
                break
        return results

    def search_with_budget(
        self,
        query_text: str,
        token_budget: int,
        top_k_pool: int = 50,
        filter: dict[str, Any] | None = None,
        budget_accountant: BudgetAccountant | None = None,
        section_name: str = "semantic_search",
    ) -> list[ChunkRow]:
        """Return chunks in relevance order that fit under ``token_budget``.

        Pulls a pool of ``top_k_pool`` candidates from the underlying
        vector search, walks them in relevance order (top-1 first),
        and includes each chunk whose ``token_count`` fits under the
        remaining budget. Chunks larger than the remaining budget are
        skipped rather than truncating the list — a smaller later
        chunk may still fit (Second Pass Q1: honour the budget while
        packing greedily by relevance, not by first-fit-then-stop).

        Packing strategy: greedy relevance-order pack. NOT knapsack-
        optimal. A pool ordered by relevance ``[95t, 55t, 45t]``
        under a 100-token cap returns ``[95t]`` even though
        ``[55t, 45t]`` = 100 would pack the cap exactly at higher
        joint relevance. A 0/1 knapsack DP over the pool would solve
        this at O(n*B); deferred to module_05's retrieve primitive
        (Flagged gap 1) where the four-level cascade owns the
        budget-aware assembly decision and can pick the packing
        strategy per level.

        When ``budget_accountant`` is supplied, each returned chunk
        is seated as a :class:`~ract.memory.budget.BudgetSection`
        named ``"{section_name}::{chunk_id[:12]}"`` so a caller who
        wants the accountant to reflect the semantic-read cost gets
        that for free.

        ``token_budget`` is the local cap for THIS call and is
        independent of any :class:`~ract.memory.budget.BudgetDeclaration`
        the accountant might carry. Callers wiring semantic search
        into a real assembly pipeline (module_09) pass the
        accountant's remaining allowance for the semantic section.
        """
        if token_budget <= 0:
            return []
        if top_k_pool <= 0:
            top_k_pool = DEFAULT_TOP_K
        vector = self._embedding.embed(query_text)
        table = self._db.open_table(self._table_name)
        builder = table.search(vector).limit(top_k_pool)
        builder = self._apply_filter(builder, filter)
        rows = builder.to_list()
        results: list[ChunkRow] = []
        remaining = token_budget
        for raw_row in rows:
            chunk = self._row_to_chunk(raw_row)
            if chunk.token_count > remaining:
                # Skip; a later smaller chunk may still fit.
                continue
            results.append(chunk)
            remaining -= chunk.token_count
            if budget_accountant is not None:
                budget_accountant.seat(
                    BudgetSection(
                        name=f"{section_name}::{chunk.chunk_id[:12]}",
                        token_count=chunk.token_count,
                        content_hash=chunk.content_hash,
                    )
                )
            if remaining <= 0:
                break
        return results

    def iter_chunks(self, filter: dict[str, Any] | None = None) -> Iterable[ChunkRow]:
        """Yield every chunk (optionally filtered).

        Diagnostic helper; module_09 uses this for the store-integrity
        probe when the operator asks the memory-discipline audit to
        walk every chunk in the store.
        """
        table = self._db.open_table(self._table_name)
        builder = table.search()
        builder = self._apply_filter(builder, filter)
        for row in builder.to_list():
            yield self._row_to_chunk(row)

    # ------------------------------------------------------------------
    # Graph enrichment (module_03 POST inbound constraint 1)
    # ------------------------------------------------------------------

    def enrich_with_graph(
        self,
        semantic_hits: list[ChunkRow],
        graph_index: Any,
        max_neighbors_per_hit: int = 3,
        include_symbol_only: bool = False,
        direction: Literal["callers", "callees", "both"] = "both",
    ) -> list[tuple[ChunkRow, list[SymbolRow]]]:
        """Attach one-hop graph neighbours to each semantic hit.

        Reads the module_03
        :class:`~ract.memory.graph_index.GraphIndex` for each hit
        symbol id and returns
        ``[(hit_chunk, [neighbour_symbol_rows...])]``. By default
        filters ``neighborhood_source='lsp'`` and drops
        ``symbol_only`` fallback edges (module_03 POST inbound
        constraint: a semantic-quality read must not silently
        include symbol-only edges). Callers opting into the
        fallback edges pass ``include_symbol_only=True``.

        Direction: ``"callers"`` walks callers of the hit;
        ``"callees"`` walks callees; ``"both"`` merges the two.
        """
        results: list[tuple[ChunkRow, list[SymbolRow]]] = []
        for hit in semantic_hits:
            neighbours: list[SymbolRow] = []
            seen: set[int] = set()

            def _record(edges: list[Any]) -> None:
                for edge in edges:
                    if (
                        not include_symbol_only
                        and edge.neighborhood_source == "symbol_only"
                    ):
                        continue
                    target_id = (
                        edge.target_symbol_id
                        if edge.source_symbol_id == hit.symbol_id
                        else edge.source_symbol_id
                    )
                    if target_id in seen or target_id == hit.symbol_id:
                        continue
                    seen.add(target_id)
                    # Look up the row through the symbol store.
                    row = self._symbol_row_by_id(target_id)
                    if row is not None:
                        neighbours.append(row)
                    if len(neighbours) >= max_neighbors_per_hit:
                        return

            if direction in ("callers", "both"):
                _record(list(graph_index.callers_of(hit.symbol_id, max_hops=1)))
            if (
                direction in ("callees", "both")
                and len(neighbours) < max_neighbors_per_hit
            ):
                _record(list(graph_index.callees_of(hit.symbol_id, max_hops=1)))
            results.append((hit, neighbours))
        return results

    def _symbol_row_by_id(self, symbol_id: int) -> SymbolRow | None:
        """Return the :class:`SymbolRow` for ``symbol_id`` or ``None``."""
        cur = self._symbol_index.connection.execute(
            "SELECT * FROM symbols WHERE id = ?", (int(symbol_id),)
        )
        raw = cur.fetchone()
        if raw is None:
            return None
        from ract.memory.symbol_index import _row_from_sqlite

        return _row_from_sqlite(raw)


def rebuild_chunk_vectors(
    chunks: list[ChunkRow], embedding: EmbeddingModel
) -> list[ChunkRow]:
    """Embed every chunk in ``chunks`` and return copies with the vector set.

    Pure helper: the builder in :mod:`ract.memory.semantic_builder`
    reads chunks off the chunker, calls this to attach vectors, then
    hands them to :meth:`SemanticIndex.insert_or_update_batch`.
    """
    if not chunks:
        return []
    texts = [chunk.body for chunk in chunks]
    vectors = embedding.embed_batch(texts)
    result: list[ChunkRow] = []
    for chunk, vec in zip(chunks, vectors, strict=True):
        result.append(chunk._replace(vector=[float(v) for v in vec]))
    return result


ChunkFilterFn = Callable[[ChunkRow], bool]


__all__ = [
    "CHUNKS_TABLE_NAME",
    "CHUNK_KINDS",
    "CURRENT_SCHEMA_VERSION",
    "ChunkFilterFn",
    "ChunkRow",
    "DEFAULT_TOP_K",
    "EmbeddingModelMismatchError",
    "LanceDbUnavailableError",
    "METADATA_FILE_NAME",
    "SemanticIndex",
    "SemanticIndexError",
    "SemanticStoreCorruptError",
    "rebuild_chunk_vectors",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
