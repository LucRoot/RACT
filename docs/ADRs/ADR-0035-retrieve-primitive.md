# ADR-0035 — Retrieve primitive with four-level cascade

Status: accepted (v0.5.0 Memory Discipline, module_05).

## Context

The memory-discipline pipeline composes three indexes (module_02
symbol, module_03 graph, module_04 semantic) plus the module_01
budget accountant. Without a retrieve primitive that unifies them,
each downstream verb (`intake` / `research` / `plan` / `edit` in
module_06) would ship a bespoke assembly path — three parallel
implementations of the same idea, each with its own bugs.

The load-bearing questions are: how to cascade under budget without
looping, how to cache safely across commits, how to render chunks in
four formats without duplicating source-slice logic, and how to make
the trace legible so a failing retrieve is diagnosable from the
returned bundle alone.

## Alternatives considered

**1. Single-shot retrieval, fail loudly on over-budget.** Cleanest
semantics: either the query fits, or the caller narrows. Rejected
because it wastes the composable-index leverage — an exact-name
match plus 40 semantic hits legitimately fits under budget if the
semantic hits render as signatures instead of full bodies. Loud
failure forces the caller to guess which knob to turn.

**2. Infinite cascade with silent drop.** Successive downgrades until
something fits. Rejected because "something fits" degrades to "empty
bundle fits under any budget" and the caller cannot tell whether the
query legitimately had no matches or whether every match was
sacrificed to fit. Silent-drop violates the memory-discipline axiom
that every drop appears in the trace.

**3. Model-in-the-loop cascade.** Each downgrade calls a summariser
to compress the level's output. Rejected because it makes every
retrieve pay for a model call under budget pressure — the exact
condition where the caller is already fighting for tokens. A
provider-driven SUMMARY format is available for callers who
explicitly opt in, but it is not part of the cascade downgrade path.

**4. Four-level cascade with per-level format table (accepted).**
Fixed four levels per master spec §Retrieval cascade. Level 1 FULL
everything. Level 2 SIGNATURE for keyword + semantic, FULL for
exact + graph. Level 3 drop semantic, SIGNATURE for graph. Level 4
SIGNATURE for exact only, drop the rest. Refuse if Level 4 still
busts budget. The cascade re-renders one candidate pool per level;
it does not re-query indexes, so growth is impossible and
termination is bounded to four steps.

## Decision

The retrieve primitive lives at `src/ract/memory/retrieve.py`. The
signature matches master spec §The retrieve primitive:

```python
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
) -> RetrievalBundle: ...
```

The cascade gathers every candidate once (exact-name via
`SymbolIndex.find_by_name`, keyword via `SymbolIndex.find_by_text`
FTS5, graph via `GraphIndex.callers_of` / `callees_of`, semantic via
`SemanticIndex.search`), then re-renders per level via a per-level
format table + a `format_chunk` call. A per-level `sum(token_count)`
fit check drives the cascade decision; a greedy relevance-order pack
runs on the level that fits.

Chunk formatter lives at `src/ract/memory/chunk.py`. The
`ChunkFormat` enum has four values (FULL / BODY_ONLY / SIGNATURE /
SUMMARY). SUMMARY delegates to a provider `summarize(chunk)` call
when one is supplied; without a provider the returned chunk carries
`body = "summary unavailable"` and `summary_pending = True`. A real
provider integration lands in module_06 alongside the four function
contracts.

Cache lives at `src/ract/memory/cache.py`. SQLite at
`.rack/cache/retrieval.db` with WAL enabled. Key digest is SHA-256
over `canonical_json(query) + repo_commit_hash`. Each entry records
the symbol id and file path list so `invalidate_by_symbol` and
`invalidate_by_file` can drop referencing entries on a watcher save.
The symbol-id match test uses bounded CSV pattern matching to avoid
false positives (id 1 must not invalidate a bundle whose ids contain
12).

Query trace lives at `src/ract/memory/query_trace.py`. The
`QueryTrace` records every `IndexHit` (kind, operation, count,
elapsed) and every `CascadeStep` (from_level, to_level, dropped
count, candidate count) plus the final level, cache-hit flag,
dropped symbols, and error marker. `to_canonical_json` renders the
trace as a byte-stable JSON string used both by the event trace and
the cache-key digest.

## Termination guarantee

The cascade re-renders one gathered pool per level; it does not
re-query indexes. The pool size at Level N+1 is at most the pool
size at Level N (the level format table only drops or shrinks;
never adds). Termination is bounded to four rendering passes plus
one refuse check. `test_cascade_never_loops_returns_or_refuses`
pins this in the sacred-spine test.

## Cache invalidation

**Per-symbol.** On a watcher save, module_02's watcher emits per
changed symbol id; the module_09 wiring calls
`invalidate_by_symbol(id)` per id. Entries whose bundle references
any of those ids drop out of the cache. A commit that touches N
symbols invalidates only the rows referencing any of those N —
incremental, not per-commit.

**Per-file.** For deletions and full-file rewrites where the symbol
id list churns, `invalidate_by_file(path)` drops every entry whose
bundle references that path. The wiring layer decides which
granularity to apply based on the watcher event kind.

**Per-commit hash.** The cache key includes `repo_commit_hash`, so a
query issued against a new commit produces a distinct key even
before the watcher fires. This closes the race window between the
commit and the watcher-driven invalidation: a cache hit against the
old commit can persist under its old key without polluting the new
commit's answers.

**Graph-edge staleness (Second Pass Q2 pre-declared):** the current
per-symbol invalidator drops a bundle only when a symbol whose id
appears in the bundle changed. If symbol B's file changes but
symbol B itself does not, and the bundle referenced symbol A via a
graph one-hop from B, the graph edge B→A may have shifted without
the bundle invalidating. Flagged gap 3 owns the deferred per-edge
invalidation surface.

## Rejected alternatives (cache)

**LRU in-memory.** Rejected because the cache needs to survive
Python restarts; a fresh CLI invocation losing every warm entry
defeats the "60-80% hit rate on repeated workflows" target.

**Full re-index on any change.** Rejected because the memory-
discipline axiom requires incremental invalidation. A monolith
rebuild on save is the shape the primitive was designed to replace.

## Chunk dedup

Bundle dedup runs on `Chunk.content_hash`, not `chunk_id` (module_04
POST inbound constraint 3). Two ChunkRow rows with identical hashes
(same method extracted at two revisions, an unchanged utility that
lives at two paths) collapse to one in the bundle. `chunk_id` is
unique per row and would defeat the dedup entirely.

## Oversize-marker handshake

Chunks whose locator carries the module_04 `oversize:` prefix
(chunker Second Pass Q3) are surfaced in the bundle with a
`truncation_notes` entry naming file, symbol, and locator. The
retrieve primitive does not silently strip the marker — callers can
opt to filter on `Chunk.oversize` before consuming the bundle.

## Nested-retrieve refuse

`retrieve(..., depth=depth)` refuses when `depth > MAX_NESTING_DEPTH`
(1) with `NestedRetrievalError`. Depth is tracked through the
`depth` parameter (explicit, per-call) rather than a thread-local
counter, so a plan that forks retrieval into concurrent workers
each receives their own depth from the parent's perspective and
cannot budget-blow via silent recursion.

## Budget-used-pct semantics

`budget_used_pct` is computed against the retrieve-local `budget`
argument (the retrieved-bundle sub-budget the caller pre-computed
from their `BudgetAccountant`), not against the whole input budget.
This matches the retrieve primitive's contract: the caller passes
in the local cap and reads back the local usage.

## Consequences

- One primitive powers every downstream verb; the four functions in
  module_06 compose against `retrieve` rather than re-implementing
  the index composition.
- Cascade termination is bounded by construction (four passes over
  one fixed pool), so a review of the primitive can enumerate every
  possible run shape.
- The query cache survives Python restarts and invalidates
  incrementally on watcher save.
- SUMMARY format is a hook for a provider integration, not a runtime
  requirement; offline callers get the placeholder body and a
  `summary_pending` flag.
- Knapsack-optimal per-level packing (module_04 POST inbound
  constraint 1) is a Flagged gap owned by module_06; the cascade
  ships greedy relevance-order pack today.

## Reference sources

- `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` §The retrieve
  primitive + §Retrieval cascade + §Cache layer + §Signals items
  3-6.
- `_BUILD/ract_v0.5.0_memory_discipline/module_05.md` (build plan +
  Lateral / Depth chains).
- ADR-0031 (budget accountant), ADR-0032 (symbol index), ADR-0033
  (graph index), ADR-0034 (semantic index) for the index
  composition constraints.
- SQLite `PRAGMA journal_mode=WAL` for concurrent cache access:
  `https://sqlite.org/wal.html`.
- Aider's repo map pattern for compressed table-of-contents chunking:
  `https://github.com/Aider-AI/aider`.

<!-- RACT 0.5.0: Retrieve primitive with four-level cascade (ADR-0035) -->
