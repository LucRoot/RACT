# ADR-0034 — Semantic index via LanceDB + local embedding model

Status: accepted (v0.5.0 Memory Discipline, module_04).

## Context

The memory-discipline pipeline needs a "give me chunks that look
like this idea" surface that composes with the module_02 symbol
index and the module_03 graph index. Symbol lookups answer exact
names; graph queries answer callable neighborhoods; neither
answers a query like "the chunk that computes an exponential
backoff" when the caller does not know a name.

The retrieve primitive in module_05 depends on this index for its
Level-2 and Level-3 cascade paths; without it the retrieve output
degrades to exact-name plus keyword-FTS only.

The load-bearing questions are: which vector store, which
embedding model, and how the store's identity is protected from
silent embedding-model swaps.

## Alternatives considered

**1. FAISS.** Mature, fast, well-tested. Rejected because FAISS
has no built-in filter-at-query-time: a caller wanting "top-10
similar chunks in file `foo.py`" has to over-fetch and filter
post-hoc. The store also needs a separate metadata layer for
the chunk row itself; the vector index is only half the story.

**2. Chroma.** Solid ecosystem. Rejected because the install is
heavy (SQLite + DuckDB + FastAPI dependencies pulled in for a
local file store) and the API drifts more per-release than
LanceDB. Grove-Sprout precedent had a similar tension; the
lighter surface won.

**3. Server-side embedding (OpenAI / Cohere / Voyage).** Rejected
because it breaks the local-first commitment. RACT's core value
is a signed, verifiable local build; a mandatory network round
per chunk on every re-index does not fit. It also introduces a
per-query cost the budget accountant cannot pre-declare.

**4. LanceDB + local sentence-transformers (accepted).** LanceDB
ships a single Python wheel, uses Arrow-native columnar storage,
supports vector search + arbitrary SQL filters in one call, and
scales to millions of rows on a laptop. The sentence-transformers
default (`bge-small-en-v1.5`, 384-dim, MIT license, CPU-friendly)
is small enough to ship in the installer and strong enough for
code-similarity search. `nomic-embed-text-v1.5` (768-dim,
Apache-2.0) is available under a config toggle for callers who
want the extra recall.

## Decision

The semantic index is a LanceDB store at `.rack/index/semantic/`
with the schema at `src/ract/memory/semantic_index.py`. The
embedding-model surface is at `src/ract/memory/embedding.py`;
`bge-small-en-v1.5` is the default. The chunker at
`src/ract/memory/chunker.py` reads module_02 `SymbolRow`
records and produces `ChunkRow` records per master spec §Chunk
discipline. The builder at `src/ract/memory/semantic_builder.py`
walks the symbol index, chunks each symbol, embeds each chunk in
batches, and inserts them into the LanceDB store. LanceDB
availability is probed at open time via
`src/ract/memory/cpu_fallback.py`; the probe reports the backend
(gpu/cpu) so the operator's log records a real answer rather than
a fiction.

## Identity + safety invariants

**Embedding-model identity.** A metadata file
`.rack/index/semantic/metadata.json` records
`{embedding_model_name, embedding_dim, schema_version, created_at}`
on first open. A re-open under a different embedder raises
`EmbeddingModelMismatchError` with a "rebuild required" message
(Lateral Chain branch E). Metadata missing while the LanceDB
table exists raises `SemanticStoreCorruptError` (Second Pass Q4).

**Symbol-index identity.** Every `ChunkRow.symbol_id` is a foreign
key to `symbols.id` from module_02. The chunker joins on
`SymbolRow.content_hash` when it needs to detect stale chunks; no
parallel symbol id space is created (module_02 POST inbound
constraint 2).

**Graph enrichment filter.** `SemanticIndex.enrich_with_graph`
filters `neighborhood_source='lsp'` by default. Callers who want
symbol-only fallback edges (a `symbol_only` self-edge from
`ract.memory.lsp_fallback`) must opt in via
`include_symbol_only=True` (module_03 POST inbound constraint 1).

**Budget respect.** `SemanticIndex.search_with_budget` accepts a
`BudgetAccountant` and seats every returned chunk as a
`BudgetSection` under the caller-supplied `section_name`. Chunks
larger than the remaining budget are skipped and a smaller later
chunk may still fit (Second Pass Q1: honour the budget while
packing greedily by relevance, not by first-fit-then-stop).

## Offline install path

The `sentence-transformers` runtime dep is an optional extra
(`pip install ract[embedding]`), not a hard runtime dep. Callers
who do not need real embeddings (offline CI, `--offline` flag,
first-run before download) can construct a
`SyntheticHashEmbedding` and open the store; the vectors are
deterministic per-text but carry no semantic meaning. Real-model
tests skip unless `RACT_EMBED_ONLINE=1`; a local weights root at
`RACT_EMBED_MODEL_ROOT=/path` bypasses the HuggingFace download.
On offline first-run, `BgeSmallEmbedding.embed` raises
`EmbeddingModelUnavailableError` with a message that names both
fallbacks (Second Pass Q2).

## Consequences

- Users get a semantic-search surface that runs offline on a
  laptop, integrates with the budget accountant, and refuses to
  silently swap vector spaces on model updates.
- Store dedup on `chunk_id` is by design: two files with
  identical utility functions produce two chunks with the same
  `content_hash` but distinct `chunk_id` values (they belong to
  distinct symbols). Deduplication at retrieve time is
  module_05's job (Lateral Chain branch D).
- LanceDB GPU wheel availability on Windows ARM64 is a
  documented degradation, not a crash. The probe reports the
  backend so the operator's log makes the mode explicit
  (Lateral Chain branch C).

## Reference sources

- `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` §Semantic index +
  §Chunk discipline + §Signals item 6.
- `_BUILD/ract_v0.5.0_memory_discipline/module_04.md` (build
  plan + Lateral / Depth chains).
- `_BUILD/ract_v0.4.0_substrate/module_04.md` (platform-
  conditional dependency handling precedent for the CPU-fallback
  probe).
- ADR-0032 (symbol index) and ADR-0033 (graph index) for the
  index composition constraints.

<!-- RACT 0.5.0: Semantic index via LanceDB + local embedding model (ADR-0034) -->
