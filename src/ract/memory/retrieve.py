"""Retrieve primitive for the memory-discipline pipeline.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
retrieve primitive + §Retrieval cascade. The primitive composes over
the three indexes (module_02 symbol, module_03 graph, module_04
semantic), runs a four-level cascade under a token budget, formats
each chunk under the caller's :class:`ChunkFormat`, and returns a
:class:`RetrievalBundle` whose members are dedup'd, budget-respecting
:class:`~ract.memory.chunk.Chunk` instances.

The cascade shrinks — never widens — with each downgrade. The four
levels track the master spec exactly:

1. FULL for every match. If under budget, return.
2. FULL for exact-name matches; SIGNATURE for keyword + semantic
   matches.
3. FULL for exact matches; SIGNATURE for one-hop graph; drop semantic.
4. SIGNATURE for exact matches; drop everything else. Return with
   ``dropped_symbols`` populated.

If Level 4 still exceeds budget, the primitive raises
:class:`BoundedContextError` and emits ``retrieval.refused``. Callers
must narrow the query rather than retry.

Inbound constraints honored (module_04 POST):

- Dedup on ``content_hash`` (constraint 3): two chunks with identical
  ``content_hash`` collapse to one in the bundle regardless of their
  ``chunk_id`` values.
- Oversize-marker handshake (constraint 2): chunks whose locator
  carries the ``oversize:`` prefix are surfaced with a truncation
  note attached to the bundle, not silently stripped.
- Knapsack packing gap (constraint 1): the cascade's per-level pack
  uses greedy relevance order today; the ADR names the deferred
  knapsack DP path and Flagged gap 1 owns it.

Inbound constraints honored (module_03 POST): none directly consumed
here — the retrieve primitive does not trigger LSP roundtrips. The
wall-clock guard for interactive ``update_file`` (module_03 POST
constraint 4) lives at the module_09 SubstrateLoop wiring layer.

Inbound constraints honored (module_02 POST): the retrieve primitive
does not offer a wait-for-index-warm mode (module_02 POST constraint
5). A stale index surfaces its stale answer with the query trace's
``error`` field left empty; module_09 wires the watcher notification
to the cache invalidator.

Lateral-Chain constraints honored (this module):

- Branch B (nested-retrieve refuse): ``depth > 1`` refuses with
  :class:`NestedRetrievalError`.
- Branch C (CORE_FIRST dedup): the CORE_FIRST strategy dedups by
  ``symbol_id`` keeping the highest-scored chunk; RELEVANCE keeps
  legitimately distinct sub-chunks.
- Branch E (index ambiguity): every :class:`Chunk` carries
  ``language`` + ``file_path``; the query trace records the source
  index per hit.
"""

from __future__ import annotations

import enum
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.chunk import (
    Chunk,
    ChunkFormat,
    chunk_from_chunk_row,
    chunk_from_symbol,
    format_chunk,
)
from ract.memory.events import (
    EventSink,
    NullEventSink,
    emit_retrieval_cascaded,
    emit_retrieval_refused,
    emit_retrieval_requested,
    emit_retrieval_satisfied,
)
from ract.memory.query_trace import CascadeStep, IndexHit, QueryTrace


TokenBudget = int
"""Alias for the retrieve primitive's local token budget.

Callers who wire retrieve into an assembly pipeline compute the
retrieved-bundle sub-budget from the caller's
:class:`~ract.memory.budget.BudgetAccountant` and pass an int.
"""


MAX_NESTING_DEPTH: int = 1
"""Mid-invocation retrieve depth ceiling (Lateral Chain B).

Plan's mid-invocation sub-retrievals are allowed at depth 1; anything
deeper refuses with :class:`NestedRetrievalError` so a recursive
budget-blow cannot occur.
"""


class BoundedContextError(RuntimeError):
    """Raised when the retrieval cascade exhausts every level.

    Carries the ``query`` that failed and the ``deepest_level``
    reached (always 4). Callers must narrow the query rather than
    retry.
    """

    def __init__(
        self, *, query: "RetrievalQuery", deepest_level: int, budget: int
    ) -> None:
        self.query = query
        self.deepest_level = deepest_level
        self.budget = budget
        super().__init__(
            f"retrieval cascade exhausted (deepest_level={deepest_level}, "
            f"budget={budget}); narrow the query and retry"
        )


class NestedRetrievalError(RuntimeError):
    """Raised on a retrieve call whose ``depth`` exceeds
    :data:`MAX_NESTING_DEPTH`.
    """

    def __init__(self, *, depth: int) -> None:
        self.depth = depth
        super().__init__(
            f"retrieve refused: depth {depth} exceeds MAX_NESTING_DEPTH "
            f"{MAX_NESTING_DEPTH}"
        )


class RetrievalStrategy(enum.Enum):
    """Cascade packing strategy.

    - ``RELEVANCE`` — pack in relevance order; keep every distinct
      sub-chunk (a large function's sub-chunks are legitimately
      different positions).
    - ``COMPREHENSIVE`` — pack every candidate; still respects the
      cascade downgrade but does not dedup by ``symbol_id``.
    - ``CORE_FIRST`` — dedup by ``symbol_id`` keeping the highest-
      scored chunk per symbol (Lateral Chain C).
    """

    RELEVANCE = "relevance"
    COMPREHENSIVE = "complete"
    CORE_FIRST = "core"


class GraphDir(enum.Enum):
    """Direction for graph-seed traversal in :class:`RetrievalQuery`."""

    CALLERS = "callers"
    CALLEES = "callees"
    BOTH = "both"


class IndexKind(enum.Enum):
    """Discriminator for :class:`IndexRef`."""

    SYMBOL = "symbol"
    GRAPH = "graph"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class IndexRef:
    """A reference to one live index instance the retrieve primitive
    may consult.

    The kind marker lets the primitive route each seed to the right
    index without inspecting the instance type. Callers pass whichever
    indexes they want available; a missing kind causes that cascade
    branch to no-op with a ``candidate_count=0`` trace hit.
    """

    kind: IndexKind
    index: Any


@dataclass(frozen=True)
class SymbolRef:
    """Reference to a symbol by id or name.

    At least one of ``symbol_id`` and ``name`` must be set. The retrieve
    primitive prefers ``symbol_id`` when both are present (id resolves
    faster and is unambiguous across files).
    """

    symbol_id: int | None = None
    name: str = ""


@dataclass(frozen=True)
class RetrievalQuery:
    """Query specification for :func:`retrieve`.

    Master spec §The retrieve primitive names every field. All lists
    default to empty tuples so a fresh :class:`RetrievalQuery` is a
    "return nothing" query rather than a "return everything" one.
    """

    symbol_names: tuple[str, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    graph_seeds: tuple[SymbolRef, ...] = field(default_factory=tuple)
    graph_direction: GraphDir = GraphDir.BOTH
    graph_hops: int = 1
    file_scope: tuple[str, ...] | None = None
    exclude_paths: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RetrievalBundle:
    """Return value of :func:`retrieve`.

    Fields mirror master spec §The retrieve primitive:

    - ``chunks`` — ordered list of :class:`Chunk` instances the bundle
      contains. Order is the packing order (RELEVANCE / COMPREHENSIVE
      / CORE_FIRST).
    - ``total_tokens`` — sum of ``chunk.token_count`` across chunks.
    - ``budget_used_pct`` — ``total_tokens / budget * 100``. Rounded
      to two decimals. ``0.0`` when ``budget`` was 0 or the bundle is
      empty. Computed against the retrieve-local ``budget`` argument
      (module_04 SP Q3-equivalent for module_05: caller pre-computes
      the retrieved-bundle sub-budget and passes it here).
    - ``dropped_count`` — count of symbol names dropped at the final
      cascade level. Includes symbols never seated and semantic-only
      matches shed at Levels 3 and 4.
    - ``dropped_symbols`` — the list of names.
    - ``query_trace`` — :class:`QueryTrace` for the call.
    - ``truncation_notes`` — one string per oversize chunk surfaced in
      the bundle (module_04 POST inbound constraint 2 handshake).
    - ``call_id`` — hex identifier for this retrieve call; used as
      ``parent_call_id`` for any nested sub-retrieve.
    """

    chunks: tuple[Chunk, ...]
    total_tokens: int
    budget_used_pct: float
    dropped_count: int
    dropped_symbols: tuple[str, ...]
    query_trace: QueryTrace
    truncation_notes: tuple[str, ...] = field(default_factory=tuple)
    call_id: str = ""
    traversal_symbol_ids: tuple[int, ...] = field(default_factory=tuple)
    """Symbol ids the retrieve visited during graph traversal but did
    NOT surface in :attr:`chunks`.

    Second Pass Q2 (PARTIAL) fix: cache invalidation must fire when
    an intermediate graph-traversal id changes, even when that id
    was a stepping stone whose neighbour ended up in the bundle. The
    cache wiring reads this list alongside :attr:`chunks`' symbol
    ids so ``invalidate_by_symbol(intermediate_id)`` drops the
    bundle even though the id is not in the surfaced chunk set.
    """


# ---------------------------------------------------------------------------
# Canonical query projection (for cache-key + event-trace)
# ---------------------------------------------------------------------------


def canonical_query_payload(query: RetrievalQuery) -> dict[str, Any]:
    """Return a canonical dict projection of ``query``.

    Sorted-key + primitive-typed so it round-trips through JSON. Used
    both as input to :func:`~ract.memory.cache._cache_key` and as the
    ``retrieval.requested`` event payload.
    """
    return {
        "symbol_names": sorted(query.symbol_names),
        "keywords": sorted(query.keywords),
        "graph_seeds": [
            {"symbol_id": seed.symbol_id, "name": seed.name}
            for seed in query.graph_seeds
        ],
        "graph_direction": query.graph_direction.value,
        "graph_hops": query.graph_hops,
        "file_scope": (
            sorted(query.file_scope) if query.file_scope is not None else None
        ),
        "exclude_paths": sorted(query.exclude_paths),
    }


# ---------------------------------------------------------------------------
# Candidate gathering
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    """Internal per-candidate record for the cascade."""

    chunk: Chunk
    origin: str  # "exact" | "keyword" | "graph" | "semantic"
    score: float


def _find_index(indexes: list[IndexRef], kind: IndexKind) -> Any | None:
    for ref in indexes:
        if ref.kind is kind:
            return ref.index
    return None


def _gather_exact(
    indexes: list[IndexRef],
    query: RetrievalQuery,
    trace_hits: list[IndexHit],
) -> list[_Candidate]:
    """Return exact-name candidates via the symbol index."""
    symbol_index = _find_index(indexes, IndexKind.SYMBOL)
    if symbol_index is None or not query.symbol_names:
        return []
    candidates: list[_Candidate] = []
    total_rows = 0
    started = time.perf_counter()
    for name in query.symbol_names:
        rows = symbol_index.find_by_name(name)
        total_rows += len(rows)
        for row in rows:
            if _excluded_path(row.file_path, query):
                continue
            source = _read_source(row.file_path)
            candidates.append(
                _Candidate(
                    chunk=chunk_from_symbol(row, source),
                    origin="exact",
                    score=1.0,
                )
            )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace_hits.append(
        IndexHit(
            index_kind="symbol",
            operation="find_by_name",
            candidate_count=total_rows,
            elapsed_ms=elapsed_ms,
        )
    )
    return candidates


def _gather_keyword(
    indexes: list[IndexRef],
    query: RetrievalQuery,
    trace_hits: list[IndexHit],
) -> list[_Candidate]:
    """Return keyword candidates via the symbol index FTS5 helper."""
    symbol_index = _find_index(indexes, IndexKind.SYMBOL)
    if symbol_index is None or not query.keywords:
        return []
    candidates: list[_Candidate] = []
    total_rows = 0
    started = time.perf_counter()
    for keyword in query.keywords:
        try:
            rows = symbol_index.find_by_text(keyword)
        except Exception:
            # A malformed FTS5 query (a lone operator, an unclosed
            # quote) must not crash retrieve. Skip and continue.
            rows = []
        total_rows += len(rows)
        for row in rows:
            if _excluded_path(row.file_path, query):
                continue
            source = _read_source(row.file_path)
            candidates.append(
                _Candidate(
                    chunk=chunk_from_symbol(row, source),
                    origin="keyword",
                    score=0.6,
                )
            )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace_hits.append(
        IndexHit(
            index_kind="symbol",
            operation="find_by_text",
            candidate_count=total_rows,
            elapsed_ms=elapsed_ms,
        )
    )
    return candidates


def _gather_graph(
    indexes: list[IndexRef],
    query: RetrievalQuery,
    trace_hits: list[IndexHit],
    traversal_ids_out: set[int] | None = None,
) -> list[_Candidate]:
    """Return graph-seeded neighbours via the graph index.

    Uses :meth:`~ract.memory.graph_index.GraphIndex.callers_of` /
    :meth:`callees_of` / :meth:`blast_radius` per ``graph_direction``.
    """
    graph_index = _find_index(indexes, IndexKind.GRAPH)
    symbol_index = _find_index(indexes, IndexKind.SYMBOL)
    if graph_index is None or not query.graph_seeds:
        return []
    candidates: list[_Candidate] = []
    total_rows = 0
    started = time.perf_counter()
    operation_label = "graph_walk"
    for seed in query.graph_seeds:
        seed_id = _resolve_seed_id(seed, symbol_index)
        if seed_id is None:
            continue
        # Record every touched id so cache invalidation fires on an
        # intermediate whose neighbour landed in the bundle (Second
        # Pass Q2 fix).
        if traversal_ids_out is not None:
            traversal_ids_out.add(seed_id)
        neighbour_ids: set[int] = set()
        try:
            if query.graph_direction in (GraphDir.CALLERS, GraphDir.BOTH):
                for edge in graph_index.callers_of(
                    seed_id, max_hops=max(1, query.graph_hops)
                ):
                    neighbour_ids.add(edge.source_symbol_id)
                    if traversal_ids_out is not None:
                        traversal_ids_out.add(edge.source_symbol_id)
                        traversal_ids_out.add(edge.target_symbol_id)
            if query.graph_direction in (GraphDir.CALLEES, GraphDir.BOTH):
                for edge in graph_index.callees_of(
                    seed_id, max_hops=max(1, query.graph_hops)
                ):
                    neighbour_ids.add(edge.target_symbol_id)
                    if traversal_ids_out is not None:
                        traversal_ids_out.add(edge.source_symbol_id)
                        traversal_ids_out.add(edge.target_symbol_id)
        except Exception:
            continue
        total_rows += len(neighbour_ids)
        if symbol_index is None:
            continue
        for nid in neighbour_ids:
            row = _lookup_symbol_by_id(symbol_index, nid)
            if row is None:
                continue
            if _excluded_path(row.file_path, query):
                continue
            source = _read_source(row.file_path)
            candidates.append(
                _Candidate(
                    chunk=chunk_from_symbol(row, source),
                    origin="graph",
                    score=0.75,
                )
            )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace_hits.append(
        IndexHit(
            index_kind="graph",
            operation=operation_label,
            candidate_count=total_rows,
            elapsed_ms=elapsed_ms,
        )
    )
    return candidates


def _gather_semantic(
    indexes: list[IndexRef],
    query: RetrievalQuery,
    trace_hits: list[IndexHit],
    top_k_pool: int = 50,
) -> list[_Candidate]:
    """Return semantic candidates via the semantic index.

    Uses the joined ``keywords`` list as the query text. When the
    ``keywords`` tuple is empty, no semantic search fires.
    """
    semantic_index = _find_index(indexes, IndexKind.SEMANTIC)
    if semantic_index is None or not query.keywords:
        return []
    query_text = " ".join(query.keywords)
    started = time.perf_counter()
    try:
        rows = semantic_index.search(query_text, top_k=top_k_pool)
    except Exception:
        rows = []
    candidates: list[_Candidate] = []
    for rank, row in enumerate(rows):
        if _excluded_path(row.file_path, query):
            continue
        chunk = chunk_from_chunk_row(row, source_index_label="semantic")
        # Rank-based score in (0, 1]: 1.0 for rank 0, decays with rank.
        score = max(0.05, 1.0 - (rank / max(1, len(rows))))
        candidates.append(_Candidate(chunk=chunk, origin="semantic", score=score))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace_hits.append(
        IndexHit(
            index_kind="semantic",
            operation="search",
            candidate_count=len(rows),
            elapsed_ms=elapsed_ms,
        )
    )
    return candidates


def _excluded_path(file_path: str, query: RetrievalQuery) -> bool:
    """Return ``True`` when ``file_path`` violates the query's scope.

    Applies ``file_scope`` (allowlist) then ``exclude_paths`` (block).
    Both use prefix match; a caller wanting glob semantics normalises
    upstream.
    """
    if query.file_scope is not None:
        if not any(file_path.startswith(scope) for scope in query.file_scope):
            return True
    for excluded in query.exclude_paths:
        if file_path.startswith(excluded):
            return True
    return False


def _resolve_seed_id(seed: SymbolRef, symbol_index: Any | None) -> int | None:
    """Resolve a :class:`SymbolRef` to a symbol id.

    Prefers ``seed.symbol_id`` when set. Otherwise looks up by name
    via the symbol index and returns the first hit (an ambiguous name
    is a caller's problem; the query trace records the graph walk
    origin so ambiguity is visible in the returned bundle).
    """
    if seed.symbol_id is not None:
        return seed.symbol_id
    if symbol_index is None or not seed.name:
        return None
    rows = symbol_index.find_by_name(seed.name)
    for row in rows:
        if row.id is not None:
            return int(row.id)
    return None


def _lookup_symbol_by_id(symbol_index: Any, symbol_id: int) -> Any | None:
    """Look up one symbol row by id via the connection's SQL.

    The module_02 SymbolIndex does not ship a public ``find_by_id``;
    the connection is available and safe for a single parameterised
    SELECT.
    """
    try:
        from ract.memory.symbol_index import _row_from_sqlite

        cur = symbol_index.connection.execute(
            "SELECT * FROM symbols WHERE id = ?", (int(symbol_id),)
        )
        row = cur.fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return _row_from_sqlite(row)


def _read_source(file_path: str) -> bytes:
    """Read the source bytes for ``file_path`` or return ``b""``.

    A missing file is a stale-index symptom (the file was deleted
    between index write and retrieve read). Rather than crash, return
    empty bytes; the resulting chunk carries an empty body and the
    caller can surface the staleness through the query trace.
    """
    from pathlib import Path

    try:
        return Path(file_path).read_bytes()
    except OSError:
        return b""


# ---------------------------------------------------------------------------
# Cascade rendering + packing
# ---------------------------------------------------------------------------


_LEVEL_FORMAT_TABLE: dict[int, dict[str, ChunkFormat | None]] = {
    1: {
        "exact": ChunkFormat.FULL,
        "keyword": ChunkFormat.FULL,
        "graph": ChunkFormat.FULL,
        "semantic": ChunkFormat.FULL,
    },
    2: {
        "exact": ChunkFormat.FULL,
        "keyword": ChunkFormat.SIGNATURE,
        "graph": ChunkFormat.FULL,
        "semantic": ChunkFormat.SIGNATURE,
    },
    3: {
        "exact": ChunkFormat.FULL,
        "keyword": ChunkFormat.SIGNATURE,
        "graph": ChunkFormat.SIGNATURE,
        "semantic": None,
    },
    4: {
        "exact": ChunkFormat.SIGNATURE,
        "keyword": None,
        "graph": None,
        "semantic": None,
    },
}


def _render_level(
    candidates: list[_Candidate],
    level: int,
    caller_format: ChunkFormat,
    provider: Any | None,
) -> tuple[list[_Candidate], list[str]]:
    """Apply the level's format table plus the caller's format.

    At Level 1 the caller's format wins (FULL by default). Downgraded
    levels enforce SIGNATURE / drop per :data:`_LEVEL_FORMAT_TABLE`.
    Returns ``(kept, dropped_names)``.
    """
    formats = _LEVEL_FORMAT_TABLE[level]
    kept: list[_Candidate] = []
    dropped_names: list[str] = []
    for cand in candidates:
        target = formats.get(cand.origin)
        if target is None:
            dropped_names.append(cand.chunk.symbol_name)
            continue
        # At Level 1, honor the caller's format for every origin so a
        # BODY_ONLY / SIGNATURE request from the caller applies before
        # the cascade downgrades.
        effective = caller_format if level == 1 else target
        rendered = format_chunk(cand.chunk, effective, provider)
        kept.append(_Candidate(chunk=rendered, origin=cand.origin, score=cand.score))
    return kept, dropped_names


def _dedup_by_content_hash(candidates: list[_Candidate]) -> list[_Candidate]:
    """Collapse candidates by ``chunk.content_hash`` keeping the first.

    Module_04 POST inbound constraint 3: dedup on ``content_hash``,
    not ``chunk_id``. Two chunks with the same content_hash (a method
    extracted at two revisions of a file, an unchanged utility that
    lives at two paths) collapse to one in the bundle.
    """
    seen: dict[str, _Candidate] = {}
    for cand in candidates:
        key = cand.chunk.content_hash or cand.chunk.chunk_id
        prior = seen.get(key)
        if prior is None or cand.score > prior.score:
            seen[key] = cand
    # Preserve original relevance order (first-encountered per key).
    order: dict[str, int] = {}
    for index, cand in enumerate(candidates):
        key = cand.chunk.content_hash or cand.chunk.chunk_id
        order.setdefault(key, index)
    return sorted(
        seen.values(), key=lambda c: order[c.chunk.content_hash or c.chunk.chunk_id]
    )


def _apply_strategy(
    candidates: list[_Candidate], strategy: RetrievalStrategy
) -> list[_Candidate]:
    """Apply the caller's :class:`RetrievalStrategy` to the candidate pool."""
    if strategy is RetrievalStrategy.CORE_FIRST:
        # Dedup by symbol_id keeping highest-scored chunk (branch C).
        best: dict[int, _Candidate] = {}
        order: dict[int, int] = {}
        for index, cand in enumerate(candidates):
            sid = cand.chunk.symbol_id
            if sid < 0:
                # Symbol id missing (test fixtures) — keep every.
                order.setdefault(id(cand), index)
                best[id(cand)] = cand
                continue
            prior = best.get(sid)
            if prior is None or cand.score > prior.score:
                best[sid] = cand
                order[sid] = index
        return sorted(best.values(), key=lambda c: order.get(c.chunk.symbol_id, 0))
    # RELEVANCE and COMPREHENSIVE keep every distinct sub-chunk.
    return list(candidates)


def _pack_under_budget(
    candidates: list[_Candidate], budget: TokenBudget
) -> tuple[list[_Candidate], int]:
    """Greedy relevance-order pack under ``budget``.

    Walks candidates in the incoming order (already sorted by score
    upstream) and includes each chunk that fits under the remaining
    budget. Chunks larger than the remaining budget are skipped rather
    than truncating the list — a smaller later chunk may still fit
    (parity with module_04's ``search_with_budget``).

    Returns ``(kept, total_tokens)``.

    Knapsack packing is a Flagged gap for module_06's plan layer,
    where the packing decision can span multiple retrieve calls.
    """
    kept: list[_Candidate] = []
    remaining = budget
    total = 0
    for cand in candidates:
        if cand.chunk.token_count <= 0:
            kept.append(cand)
            continue
        if cand.chunk.token_count > remaining:
            continue
        kept.append(cand)
        total += cand.chunk.token_count
        remaining -= cand.chunk.token_count
        if remaining <= 0:
            break
    return kept, total


def _budget_pct(total_tokens: int, budget: TokenBudget) -> float:
    if budget <= 0:
        return 0.0
    return round((total_tokens / budget) * 100.0, 2)


def _fresh_call_id() -> str:
    return uuid.uuid4().hex


def _collect_truncation_notes(chunks: list[_Candidate]) -> list[str]:
    """Return one note per oversize chunk surfaced in the bundle.

    Module_04 POST inbound constraint 2 handshake: oversize chunks are
    surfaced with a note rather than silently stripped. The retrieve
    caller can opt to exclude them by filtering on
    :attr:`Chunk.oversize` before consuming the bundle.
    """
    notes: list[str] = []
    for cand in chunks:
        if cand.chunk.oversize:
            notes.append(
                f"oversize:{cand.chunk.file_path}:{cand.chunk.symbol_name}"
                f":{cand.chunk.chunk_locator}"
            )
    return notes


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def retrieve(
    query: RetrievalQuery,
    indexes: list[IndexRef],
    budget: TokenBudget,
    format: ChunkFormat = ChunkFormat.FULL,
    strategy: RetrievalStrategy = RetrievalStrategy.RELEVANCE,
    *,
    sink: EventSink | None = None,
    provider: Any | None = None,
    depth: int = 0,
    parent_call_id: str = "",
) -> RetrievalBundle:
    """Run the four-level retrieval cascade and return a
    :class:`RetrievalBundle`.

    See module docstring for the cascade shape and the honored
    inbound-constraint list.

    Nested-retrieve refuse: a ``depth > MAX_NESTING_DEPTH`` call
    raises :class:`NestedRetrievalError` before touching any index.

    Empty-index guard: when no candidates land at Level 1 for any
    origin, the bundle returns empty with
    ``query_trace.error = "index_not_populated"`` if every reachable
    index reported zero rows; ``error`` stays empty when the indexes
    returned rows but every one filtered out under
    ``file_scope`` / ``exclude_paths``.
    """
    if depth > MAX_NESTING_DEPTH:
        raise NestedRetrievalError(depth=depth)

    call_id = _fresh_call_id()
    active_sink = sink or NullEventSink()

    canonical_query = canonical_query_payload(query)
    emit_retrieval_requested(
        active_sink,
        {
            "call_id": call_id,
            "parent_call_id": parent_call_id,
            "depth": depth,
            "query": canonical_query,
            "budget": budget,
            "format": format.value,
            "strategy": strategy.value,
        },
    )

    trace_hits: list[IndexHit] = []
    trace_cascade: list[CascadeStep] = []
    traversal_ids: set[int] = set()

    # ------------------------------------------------------------------
    # Gather every candidate from every reachable index. The cascade
    # shrinks by re-rendering the same pool; it does not re-query.
    # ------------------------------------------------------------------
    exact = _gather_exact(indexes, query, trace_hits)
    keyword = _gather_keyword(indexes, query, trace_hits)
    graph = _gather_graph(indexes, query, trace_hits, traversal_ids_out=traversal_ids)
    semantic = _gather_semantic(indexes, query, trace_hits)
    all_candidates = exact + keyword + graph + semantic

    total_index_rows = sum(hit.candidate_count for hit in trace_hits)
    total_after_scope = len(all_candidates)

    empty_error = ""
    if total_index_rows == 0:
        # No index returned any row for the query. Either the indexes
        # are empty (fresh repo, no ract memory init) or every seed
        # missed. The error field lets the caller distinguish structural
        # emptiness from "nothing matched".
        empty_error = "index_not_populated"
    elif total_after_scope == 0:
        empty_error = "all_candidates_out_of_scope"

    if not all_candidates:
        trace = QueryTrace(
            index_hits=tuple(trace_hits),
            cascade_steps=tuple(trace_cascade),
            final_level=1,
            cache_hit=False,
            dropped_symbols=tuple(),
            error=empty_error,
            depth=depth,
            parent_call_id=parent_call_id,
        )
        bundle = RetrievalBundle(
            chunks=tuple(),
            total_tokens=0,
            budget_used_pct=0.0,
            dropped_count=0,
            dropped_symbols=tuple(),
            query_trace=trace,
            truncation_notes=tuple(),
            call_id=call_id,
            traversal_symbol_ids=tuple(sorted(traversal_ids)),
        )
        emit_retrieval_satisfied(
            active_sink,
            {
                "call_id": call_id,
                "total_tokens": 0,
                "budget_used_pct": 0.0,
                "final_level": 1,
                "error": empty_error,
            },
        )
        return bundle

    # ------------------------------------------------------------------
    # Four-level cascade. The cascade condition is: does the fully
    # rendered level content fit under budget? A greedy per-level pack
    # runs after the fit check so partial pack does not silently mask
    # cascade need.
    # ------------------------------------------------------------------
    last_level = 0
    for level in (1, 2, 3, 4):
        last_level = level
        kept, dropped_names = _render_level(all_candidates, level, format, provider)
        # Apply strategy dedup + content-hash dedup.
        kept = _dedup_by_content_hash(kept)
        kept = _apply_strategy(kept, strategy)
        unpacked_total = sum(cand.chunk.token_count for cand in kept)
        fits_fully = unpacked_total <= budget

        if fits_fully:
            packed = kept
            total_tokens = unpacked_total
            combined_dropped = list(dict.fromkeys(dropped_names))
            return _build_and_emit(
                active_sink=active_sink,
                packed=packed,
                total_tokens=total_tokens,
                combined_dropped=combined_dropped,
                trace_hits=trace_hits,
                trace_cascade=trace_cascade,
                level=level,
                depth=depth,
                parent_call_id=parent_call_id,
                budget=budget,
                call_id=call_id,
                traversal_ids=traversal_ids,
            )

        if level < 4:
            # Cascade down.
            step = CascadeStep(
                from_level=level,
                to_level=level + 1,
                dropped_symbols_count=len(dropped_names),
                candidate_count=len(kept),
            )
            trace_cascade.append(step)
            emit_retrieval_cascaded(
                active_sink,
                {
                    "call_id": call_id,
                    "from_level": step.from_level,
                    "to_level": step.to_level,
                    "dropped_symbols_count": step.dropped_symbols_count,
                    "candidate_count": step.candidate_count,
                },
            )
            continue

        # Level 4 exceeded budget under strict fit-fully. Best-effort
        # greedy pack: seat as many exact-match SIGNATUREs as fit. If
        # nothing fits, refuse.
        packed, total_tokens = _pack_under_budget(kept, budget)
        if not packed:
            refuse_payload = {
                "call_id": call_id,
                "deepest_level": last_level,
                "budget": budget,
                "query": canonical_query,
            }
            emit_retrieval_refused(active_sink, refuse_payload)
            raise BoundedContextError(
                query=query, deepest_level=last_level, budget=budget
            )
        packed_symbol_names = {cand.chunk.symbol_name for cand in packed}
        skipped_names = [
            cand.chunk.symbol_name
            for cand in kept
            if cand.chunk.symbol_name not in packed_symbol_names
        ]
        combined_dropped = list(dict.fromkeys(dropped_names + skipped_names))
        return _build_and_emit(
            active_sink=active_sink,
            packed=packed,
            total_tokens=total_tokens,
            combined_dropped=combined_dropped,
            trace_hits=trace_hits,
            trace_cascade=trace_cascade,
            level=4,
            depth=depth,
            parent_call_id=parent_call_id,
            budget=budget,
            call_id=call_id,
            traversal_ids=traversal_ids,
        )

    # Unreachable: the loop returns or raises before this line. Kept
    # as a defensive assert to make static analysis happy.
    raise BoundedContextError(query=query, deepest_level=last_level, budget=budget)


def _build_and_emit(
    *,
    active_sink: EventSink,
    packed: list[_Candidate],
    total_tokens: int,
    combined_dropped: list[str],
    trace_hits: list[IndexHit],
    trace_cascade: list[CascadeStep],
    level: int,
    depth: int,
    parent_call_id: str,
    budget: TokenBudget,
    call_id: str,
    traversal_ids: set[int],
) -> RetrievalBundle:
    truncation_notes = _collect_truncation_notes(packed)
    trace = QueryTrace(
        index_hits=tuple(trace_hits),
        cascade_steps=tuple(trace_cascade),
        final_level=level,
        cache_hit=False,
        dropped_symbols=tuple(combined_dropped),
        error="",
        depth=depth,
        parent_call_id=parent_call_id,
    )
    bundle = RetrievalBundle(
        chunks=tuple(cand.chunk for cand in packed),
        total_tokens=total_tokens,
        budget_used_pct=_budget_pct(total_tokens, budget),
        dropped_count=len(combined_dropped),
        dropped_symbols=tuple(combined_dropped),
        query_trace=trace,
        truncation_notes=tuple(truncation_notes),
        call_id=call_id,
        traversal_symbol_ids=tuple(sorted(traversal_ids)),
    )
    emit_retrieval_satisfied(
        active_sink,
        {
            "call_id": call_id,
            "total_tokens": total_tokens,
            "budget_used_pct": bundle.budget_used_pct,
            "final_level": level,
            "dropped_count": bundle.dropped_count,
        },
    )
    return bundle


# ---------------------------------------------------------------------------
# Cache re-hydration helpers
# ---------------------------------------------------------------------------


def bundle_to_cache_payload(bundle: RetrievalBundle) -> dict[str, Any]:
    """Return a JSON-friendly projection of ``bundle`` for the cache.

    Used by callers who wrap :func:`retrieve` with a
    :class:`~ract.memory.cache.RetrievalCache`. The projection omits
    the call_id (fresh per retrieve) and preserves every other field
    verbatim.
    """
    return {
        "chunks": [_chunk_to_dict(chunk) for chunk in bundle.chunks],
        "total_tokens": bundle.total_tokens,
        "budget_used_pct": bundle.budget_used_pct,
        "dropped_count": bundle.dropped_count,
        "dropped_symbols": list(bundle.dropped_symbols),
        "truncation_notes": list(bundle.truncation_notes),
        "traversal_symbol_ids": list(bundle.traversal_symbol_ids),
        "query_trace": {
            "final_level": bundle.query_trace.final_level,
            "cache_hit": bundle.query_trace.cache_hit,
            "dropped_symbols": list(bundle.query_trace.dropped_symbols),
            "error": bundle.query_trace.error,
            "depth": bundle.query_trace.depth,
            "parent_call_id": bundle.query_trace.parent_call_id,
            "index_hits": [
                {
                    "index_kind": hit.index_kind,
                    "operation": hit.operation,
                    "candidate_count": hit.candidate_count,
                    "elapsed_ms": hit.elapsed_ms,
                }
                for hit in bundle.query_trace.index_hits
            ],
            "cascade_steps": [
                {
                    "from_level": step.from_level,
                    "to_level": step.to_level,
                    "dropped_symbols_count": step.dropped_symbols_count,
                    "candidate_count": step.candidate_count,
                }
                for step in bundle.query_trace.cascade_steps
            ],
        },
    }


def cache_payload_to_bundle(payload: dict[str, Any]) -> RetrievalBundle:
    """Re-hydrate a bundle from a
    :func:`bundle_to_cache_payload` projection.

    The ``call_id`` is regenerated so each re-hydration produces a
    fresh id (a cached bundle is a new retrieve from the caller's
    view). :attr:`QueryTrace.cache_hit` is set to ``True`` so the
    caller can see the bundle came from the cache without a separate
    signal.
    """
    trace_payload = payload.get("query_trace", {})
    trace = QueryTrace(
        index_hits=tuple(
            IndexHit(
                index_kind=hit["index_kind"],
                operation=hit["operation"],
                candidate_count=int(hit["candidate_count"]),
                elapsed_ms=int(hit["elapsed_ms"]),
            )
            for hit in trace_payload.get("index_hits", [])
        ),
        cascade_steps=tuple(
            CascadeStep(
                from_level=int(step["from_level"]),
                to_level=int(step["to_level"]),
                dropped_symbols_count=int(step["dropped_symbols_count"]),
                candidate_count=int(step["candidate_count"]),
            )
            for step in trace_payload.get("cascade_steps", [])
        ),
        final_level=int(trace_payload.get("final_level", 0)),
        cache_hit=True,
        dropped_symbols=tuple(trace_payload.get("dropped_symbols", [])),
        error=str(trace_payload.get("error", "")),
        depth=int(trace_payload.get("depth", 0)),
        parent_call_id=str(trace_payload.get("parent_call_id", "")),
    )
    chunks = tuple(_dict_to_chunk(raw) for raw in payload.get("chunks", []))
    return RetrievalBundle(
        chunks=chunks,
        total_tokens=int(payload.get("total_tokens", 0)),
        budget_used_pct=float(payload.get("budget_used_pct", 0.0)),
        dropped_count=int(payload.get("dropped_count", 0)),
        dropped_symbols=tuple(payload.get("dropped_symbols", [])),
        query_trace=trace,
        truncation_notes=tuple(payload.get("truncation_notes", [])),
        call_id=_fresh_call_id(),
        traversal_symbol_ids=tuple(
            int(sid) for sid in payload.get("traversal_symbol_ids", [])
        ),
    )


def _chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "symbol_id": chunk.symbol_id,
        "symbol_name": chunk.symbol_name,
        "file_path": chunk.file_path,
        "language": chunk.language,
        "kind": chunk.kind,
        "signature": chunk.signature,
        "body": chunk.body,
        "content_hash": chunk.content_hash,
        "token_count": chunk.token_count,
        "oversize": chunk.oversize,
        "chunk_locator": chunk.chunk_locator,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "summary_pending": chunk.summary_pending,
        "metadata": dict(chunk.metadata),
    }


def _dict_to_chunk(raw: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=str(raw["chunk_id"]),
        symbol_id=int(raw.get("symbol_id", -1)),
        symbol_name=str(raw.get("symbol_name", "")),
        file_path=str(raw.get("file_path", "")),
        language=raw.get("language"),
        kind=str(raw.get("kind", "")),
        signature=str(raw.get("signature", "")),
        body=str(raw.get("body", "")),
        content_hash=str(raw.get("content_hash", "")),
        token_count=int(raw.get("token_count", 0)),
        oversize=bool(raw.get("oversize", False)),
        chunk_locator=str(raw.get("chunk_locator", "0/1")),
        start_line=raw.get("start_line"),
        end_line=raw.get("end_line"),
        summary_pending=bool(raw.get("summary_pending", False)),
        metadata=dict(raw.get("metadata", {})),
    )


def bundle_symbol_ids(bundle: RetrievalBundle) -> list[int]:
    """Return sorted unique symbol ids referenced by ``bundle``.

    Used by callers wiring the cache: each entry records the symbol
    id list so :meth:`~ract.memory.cache.RetrievalCache.invalidate_by_symbol`
    can drop entries that reference a changed symbol.

    Second Pass Q2 (PARTIAL) fix: the returned set is the UNION of
    :attr:`Chunk.symbol_id` on surfaced chunks AND
    :attr:`RetrievalBundle.traversal_symbol_ids` (intermediate ids
    visited during graph traversal). A change to an intermediate id
    whose neighbour ended up in the bundle correctly fires
    invalidation, closing the graph-edge staleness case the reviewer
    surfaced.
    """
    chunk_ids = {chunk.symbol_id for chunk in bundle.chunks if chunk.symbol_id >= 0}
    traversal = {sid for sid in bundle.traversal_symbol_ids if sid >= 0}
    return sorted(chunk_ids | traversal)


def bundle_file_paths(bundle: RetrievalBundle) -> list[str]:
    """Return sorted unique file paths referenced by ``bundle``."""
    return sorted({chunk.file_path for chunk in bundle.chunks if chunk.file_path})


def query_digest(query: RetrievalQuery) -> str:
    """Return the SHA-256 hex digest of the canonical query projection.

    Used for a short-form cache-key surface exposed to diagnostics.
    """
    projection = canonical_query_payload(query)
    import json as _json

    body = _json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


__all__ = [
    "BoundedContextError",
    "GraphDir",
    "IndexKind",
    "IndexRef",
    "MAX_NESTING_DEPTH",
    "NestedRetrievalError",
    "RetrievalBundle",
    "RetrievalQuery",
    "RetrievalStrategy",
    "SymbolRef",
    "TokenBudget",
    "bundle_file_paths",
    "bundle_symbol_ids",
    "bundle_to_cache_payload",
    "cache_payload_to_bundle",
    "canonical_query_payload",
    "query_digest",
    "retrieve",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
