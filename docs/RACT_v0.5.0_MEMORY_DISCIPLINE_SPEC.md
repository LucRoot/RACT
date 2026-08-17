# RACT v0.5.0 Memory Discipline Spec

**Version:** 0.5.0 (pipeline guidance)
**Predecessor:** v0.4.1 Intent-Fidelity (tagged `v0.4.1`, 2026-08-17)
**Tag target:** `v0.5.0`
**Prepared for:** Lucas Root
**Sacred:** Rootknot (three-signature schema — generator, environment, anti-lazy). No signature added, removed, or reshaped in this pipeline. The wordlist gate at `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files` stays intact. Author-name-free tree stays intact.

---

## Why this pipeline exists

The v0.4.x pipelines gave RACT an environment-authoritative loop: compiled acceptance predicates decide T1, worktree-per-step transactions carry rollback, OS-enforced sandbox and typed action union enforce shape, the hash-chained event log carries provenance, held-out predicates and mutation-kill enforce anti-lazy. What v0.4.x did not give RACT is a discipline for how the loop assembles the context it feeds to the model at every step. Every provider call today builds its context ad hoc: some paths read whole files, some paths read a plan and a partial snapshot, some paths reach into `symbol_graph.py` for a shallow neighborhood. There is no declared token budget per call, no accountant that rejects an over-budget assembly, no retrieval primitive that composes across a symbol index, a graph index, and a semantic index under one contract, and no self-adjustment layer that measures whether the model actually uses the context RACT paid for.

The v0.5.0 pipeline lands that discipline as a first-class substrate under the SubstrateLoop the executor-adapter shim already constructs. Every function that reaches the model has a declared budget, a retrieval contract, and a chunk shape. Every retrieval cascades through downgrades before dropping content. Every index update is incremental. Every failure emits a structured record that feeds a nightly self-adjustment pass. The point is not to make the model smarter about context; the point is to stop the harness from silently overspending context on every step and to make the assembly a fact the operator can audit, not a side effect of whichever tool call happened to build the prompt.

v0.5.0 is scoped to the load-bearing half of the design and defers the remainder to v0.6. See §Bounded scope below for the exact split.

---

## Design axioms

Six invariants everything else derives from. A module that would break any of these halts and files an ADR before proceeding.

1. **Budget is the primary constraint.** Every function that reaches a model declares a token budget (input min/target/max, reasoning headroom, hard ceiling). The harness enforces the ceiling as a hard error. Exceeding the ceiling is not "degraded"; it is refused, and the composition layer above decides whether to iterate, split, or escalate.
2. **Load functions, never files.** The atomic unit of code retrieval is the AST node (function, method, class, module-level declaration). Files are directory constructs for humans. The retrieval layer reasons at the semantic unit.
3. **Indexes are cheap, model calls are expensive.** Query indexes ten times to load code once. A well-designed pipeline runs dozens of index queries per model call.
4. **Retrieval is a first-class primitive.** Functions can retrieve mid-execution under a scoped budget. Retrieval is continuous, not a one-shot pre-load.
5. **The plan is the contract.** Edit trusts Plan to identify correct targets. Plan trusts Research to identify correct scope. Each function operates within a contract narrowed by the previous phase, and the closure is inspectable through the event trace.
6. **Self-adjustment is measured, not guessed.** The harness runs continuous quality probes (needle, coherence, adherence) against the configured provider. Budgets derive from measured behavior on the actual provider, not from static defaults.

---

## Non-negotiable invariants

The following hold across every module in this pipeline. A module that would break any of them halts and files an ADR before proceeding.

1. **Rootknot is sacred.** The three-signature schema (generator, environment, anti-lazy) carries forward unchanged. Memory-discipline records that attest a retrieval bundle land as an extension to the generator signature's payload (a new field, not a new signature); the extension is optional and older sidecars continue to verify under the compatibility reader path.
2. **Definition of Done is a yes/no test.** Every module's DoD is a boolean checklist a cold reader can execute. Qualitative bullets are forbidden. Where prose is needed it lands in Flagged gaps, not in the DoD.
3. **`pytest -q`, `ruff check`, `mypy` green at every commit.** Not "green by close of pipeline." Green at every commit. A scaffolding commit that would break the suite lands behind a feature flag defaulting to off.
4. **Cron watchdog + per-sub-task cadence.** The pipeline runs under a scheduled watchdog that fires resume + alignment pulses. The pulse reads `active_module` from `_BUILD/ract_v0.5.0_memory_discipline/build_state.md` and continues from the first not-yet-DONE step. Operator is designer and course-corrector, not per-module green light.
5. **Local commits only.** No `git push` from the pipeline. Tag `v0.5.0` at close is local; publication is a separate operator handshake per the v0.4.1 close convention.
6. **No new runtime dependency without a fresh ADR.** v0.4.1 baseline dependencies stay. Memory discipline adds at least `tree-sitter` (plus language grammars for Python/TypeScript/Rust/Go), `multilspy`, and `lancedb`. `dspy` and `outlines` remain optional (dev-extras) until v0.6 lands their integration. Each addition to `[project.dependencies]` requires an ADR with rejected alternatives.
7. **No closed-IP terms.** The wordlist gate at `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files` runs zero-tolerance on the 25-term list carried forward from v0.4.1. No module fragment or fix commit re-introduces any term.
8. **Sacred spine is enforced by tests, not by narrative.** §Sacred spine below lists the load-bearing invariants; every one has a named test file that would fire if the invariant were violated.

---

## Bounded scope

v0.5.0 ships the load-bearing half of the memory-discipline surface. v0.6 hardens the remainder. The split is chosen so v0.5.0 delivers a complete usable substrate (budgets, three indexes, retrieve, four core functions, four playbooks, self-adjustment probes) that later work extends without reshaping.

### v0.5.0 scope (ships in this pipeline)

- **Token budget system** (module_01). BudgetDeclaration YAML schema, per-function default registry, BudgetAccountant with hard-ceiling enforcement, composition override, runtime narrowing.
- **Symbol index** (module_02). SQLite schema, tree-sitter parsing for Python/TypeScript/Rust/Go, incremental file watcher, query API (name/pattern/file/FTS/hash).
- **Graph index** (module_03). SQLite schema, `multilspy` LSP client, edge population and update, query API (callers/callees/blast-radius/path/orphans/hotspots).
- **Semantic index** (module_04). LanceDB store, one embedding per AST chunk, local embedding model (`bge-small-en-v1.5` default; `nomic-embed-text-v1.5` alternative under a config toggle), query API with token-bounded search.
- **Retrieve primitive** (module_05). `retrieve(query, indexes, budget, format, strategy) -> RetrievalBundle`, four-level cascade (full → mixed → signature-neighborhood → drop), query cache keyed on `(query_hash, repo_commit_hash)`, chunk formatter with four formats (FULL/BODY_ONLY/SIGNATURE/SUMMARY).
- **Four functions** (module_06). `intake`, `research`, `plan`, `edit` — the four verbs that carry a complete change from user request through to a candidate diff. `verify`, `review`, `commit`, `document` defer to v0.6.
- **Four playbooks** (module_07). Refactor: rename symbol; refactor: extract method; bug fix; unit test. `security_audit`, `feature_addition_endpoint`, `migration_dep`, `code_review_pr`, `perf_optimization`, `dead_code`, `schema_migration`, `config_change` defer to v0.6.
- **Self-adjustment probes** (module_08). Needle, coherence, adherence probe suites; failure-record aggregation; per-repo fingerprint (function length, LSP response time, test runtime). Nightly recompilation, drift detection defer to v0.6.
- **Integration with existing RACT** (module_09). SubstrateLoop wires the retrieval bundle onto every `SubstrateStepSpec`; Rootknot generator-signature payload extension for retrieval attestation; new event kinds (`budget.declared`, `budget.exceeded`, `retrieval.requested`, `retrieval.satisfied`, `retrieval.cascaded`, `retrieval.refused`, `probe.evaluated`); ALM Gate G7 (companion provider) extension for `edit` function.
- **Release close** (module_10). CHANGELOG `[0.5.0]`, README refresh, ROADMAP compilation, version triple bump, combined signal sweep (43 v0.4.1 signals + 13 new §Signals list), tag `v0.5.0`, handshake-gated push.

### v0.6 hardening (deferred)

- `verify`, `review`, `commit`, `document` functions (module_06 in the v0.6 pipeline).
- Eight remaining playbooks (security audit, feature endpoint, migration, code review, perf, dead code, schema migration, config change).
- DSPy signature compilation with weekly recompile and diff report.
- Outlines-based structured generation for `edit` output (v0.5.0 uses AST validation + retry on parse error; v0.6 adds grammar-constrained generation).
- Drift detector (23-dimensional behavioral vectors, statistical process control on weekly distributions).
- Automated nightly review queue that applies runtime budget narrowing.
- Repo fingerprint feedback loop that adjusts retrieval defaults per repo.
- Cross-language coverage for the graph index beyond Python/TypeScript/Rust/Go (Java, Kotlin, C#, C/C++).
- OTLP export of `retrieval.*` and `budget.*` events (event kinds land in v0.5.0; the OTLP mapping lands in v0.6).

**Justification for the cut.** The four v0.5.0 functions carry a full change from request through to candidate diff. `verify` already runs deterministically in the current tree (tree-sitter parse, LSP diagnostics, lint, ast-grep queries, pytest); wrapping it in a memory-discipline contract adds shape but no capability, and can wait. `review`, `commit`, `document` sit downstream of `verify` and are pure composition; they defer without blocking any v0.5.0 use case. The four v0.5.0 playbooks cover the two most common refactor shapes (rename, extract), plus bug fix, plus unit test — the four workflows that dominate any real coding session. The remaining eight playbooks are shape-work on top of the same primitives; each is a v0.6 module in its own right.

---

## Integration surface with existing RACT

Memory discipline is not greenfield. It plugs into the SubstrateLoop the executor-adapter shim already constructs. This section names every seam.

### Function contracts relative to the SubstrateLoop

The four v0.5.0 functions map onto the existing loop as follows:

- `intake` runs **before** `SubstrateLoop.run_step` is entered for the first step of a new run. Its output (a WorkOrder record) becomes an input to `IntentCompiler.compile` alongside the intent text; the WorkOrder's `scope_hints` feed the compiler's touched-surface computation.
- `research` runs **as** the first `SubstrateStepSpec` in a run when the WorkOrder is `research_needed=true`. Its output (a ResearchBundle record) is persisted to `evals/runs/<run_id>/research.json` and referenced by the next step's `SubstrateStepSpec.metadata`.
- `plan` runs **as** the second `SubstrateStepSpec`. Its output (a ChangePlan record) is persisted to `evals/runs/<run_id>/plan.json` and referenced by every subsequent edit step.
- `edit` runs **as** each edit `SubstrateStepSpec` under the plan. One edit step per plan-designated edit target. The `SubstrateStepSpec.predicates` are the plan's `verification_criteria` compiled into `AcceptancePredicate` values; the transaction commits only when they pass.

Every function is a `SubstrateStepSpec` under the existing loop. Retrieval happens **inside** the step runner the loop calls; the runner reads `SubstrateStepSpec.metadata["retrieval_bundle"]` (populated by the memory-discipline layer before `run_step`) and passes it to the model call. No change to `SubstrateLoop.run_step`'s public signature.

### Indexes relative to existing surfaces

The three indexes coexist with existing surfaces. Overlap and delta:

- **Symbol index** (module_02) supersedes `src/ract/symbol_graph.py` for symbol lookup by name/pattern/file. The existing `SymbolGraph` stays in the tree for the callers that read it today; module_02 lands the new index as a parallel surface and module_09 migrates one call site (`src/ract/planner.py`'s symbol resolution) as the reference migration. Full cutover is v0.6.
- **Graph index** (module_03) supersedes `src/ract/dependency_graph.py` for call-graph queries. Same parallel-then-migrate pattern.
- **Semantic index** (module_04) is net new. No existing semantic-search surface in the tree.

The existing `src/ract/core/predicate.py` (AcceptanceSuite) and `src/ract/trace/events.py` (event trace) are untouched. Memory-discipline events extend the closed EventKind vocabulary in `events.py` by seven kinds (see §Signals); the AcceptanceSuite is consumed by `edit`'s predicate wiring in module_09 but its shape does not change.

### `retrieve` relative to existing CLI verbs

The current CLI verbs relevant to retrieval are `ract retrieval` (which today invokes `src/ract/retrieval_adapter.py`'s `KeywordRetrievalAdapter` and `WebSearchAdapter`). Memory discipline extends this verb with a subcommand `ract retrieval query --budget <n> --format <fmt> --strategy <s>` that invokes the new `retrieve` primitive against the three new indexes. The existing `KeywordRetrievalAdapter` and `WebSearchAdapter` stay; they are the fallback the new primitive routes to when no index is populated (e.g., a fresh repo before the initial index build).

Other verbs that touch context assembly:

- `ract run` (the primary run verb) reads the plan and the current step, then calls the model. Module_09 wires `ract run` to build the retrieval bundle from the step's declared budget and function contract before the model call.
- `ract plan` (the `plan analyze` / `plan replay` verbs) reads a saved plan. No memory-discipline change; the plan is already a data structure.
- `ract explain` uses whole-file context today. Module_09 gates `ract explain` behind the new `explain` function contract, which uses `SIGNATURE` chunks by default and `BODY_ONLY` on the explicitly named symbol. Deferred to v0.6 if the wiring bloats module_09; landed in module_09 if it fits.
- `ract report` reads the event log. Module_09 extends the projection to include the seven new event kinds.

### Rootknot attestation for retrieval bundles

The three-signature Rootknot schema is untouched. The generator signature's payload gains an optional `retrieval_attestation` field: SHA-256 of the retrieval bundle the step's model call consumed. The field is written by the memory-discipline layer when it populates the step spec, read back by the Rootknot signer at commit time, and appears in `evals/runs/<run_id>/rootknot.json` under the generator payload. Older Rootknots without the field continue to verify under the existing compatibility reader path; a v2 or v3 Rootknot with `retrieval_attestation=None` is a valid record for a step that had no retrieval bundle (a deterministic non-model step). No new signature. No schema-version bump.

The environment signature and anti-lazy signature are untouched by this pipeline.

### ALM gate interactions

The eight ALM gates (G1-G8) interact with memory discipline as follows:

- **G1** (held-out predicate enforcement) is orthogonal. Held-out predicates evaluate against the workspace snapshot after `edit`; memory discipline does not change what predicates are visible or held-out.
- **G2** (mutation-kill threshold) is orthogonal. Mutation testing runs against the touched files after `edit`; memory discipline does not change the mutation runner.
- **G3** (coverage delta) applies to `verify` (deferred to v0.6).
- **G4** (test-integrity) applies to `verify` (deferred to v0.6).
- **G5** (weak-assertion detection) applies to `verify` (deferred to v0.6).
- **G6** (under-edit closure) extends to `edit`. Module_09 wires `edit`'s output through G6's under-edit closure check before the transaction commits; a plan that names files outside the retrieval bundle raises `LazinessViolatedError`.
- **G7** (companion provider) extends to `edit`. Module_09 wires `edit`'s output through the companion provider for a second-pass review before commit. This is the load-bearing wiring for memory discipline: without G7, `edit`'s single-pass model call is unattested.
- **G8** (effort reconciliation) is orthogonal. Applies at completion; memory discipline does not change the completion gate.

The G6 and G7 extensions land in module_09.

---

## The token budget system

Every function that reaches a model declares a budget structure:

```yaml
function: research
budget:
  input:
    min: 500
    target: 3000
    max: 4000
  output:
    min: 500
    target: 2000
    max: 3000
  reasoning_headroom: 2000
  hard_ceiling: 8000
```

Meaning:

- `input.target` is what the harness aims to provide.
- `input.max` is the ceiling above which the invocation is refused with `BudgetExceededError`.
- `reasoning_headroom` reserves space for generation.
- `hard_ceiling` is the total context including system prompt, function contract, state context, retrieved bundle, and invocation input.

### Budget sources

Three sources feed the budget for any invocation, in precedence order:

1. **Function default** from the registry at `src/ract/memory/budget_defaults.yaml`.
2. **Composition override** from the playbook YAML for the current use case.
3. **Runtime adjustment** from the self-adjustment layer.

Runtime adjustment **always narrows, never widens**. Widening is a design change and requires a fresh function-default commit.

### Context composition

The context assembled for any invocation has a fixed shape:

```
[system_prompt]        # function-specific, versioned in src/ract/memory/prompts/
[function_contract]    # what this function must and must not do
[state_context]        # relevant working/session memory
[retrieved_bundle]     # retrieved code and metadata
[invocation_input]     # specific input for this call
```

Each section has a sub-budget. `state_context` is bounded at 15% of `input` budget. `retrieved_bundle` gets the rest of `input` budget after `system_prompt`, `function_contract`, and `state_context` are seated.

### Enforcement

The `BudgetAccountant` runs per invocation. Every write into the assembled context passes through the accountant. On over-target: the accountant invokes the retrieval cascade's downgrade path. On over-max: the accountant raises `BudgetExceededError` with the offending section named. On over-ceiling: the accountant refuses the invocation before the model call and emits `budget.exceeded` to the event trace.

---

## The three indexes

### Symbol index

SQLite schema at `src/ract/memory/symbol_index_schema.sql`:

```sql
CREATE TABLE symbols (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,  -- function, class, method, constant, type, interface
  file_path TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  signature TEXT,
  docstring TEXT,
  visibility TEXT,
  parent_symbol_id INTEGER,
  language TEXT,
  content_hash TEXT,
  token_count INTEGER,
  updated_at INTEGER
);

CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_kind ON symbols(kind);
CREATE INDEX idx_symbols_file ON symbols(file_path);
CREATE VIRTUAL TABLE symbols_fts USING fts5(name, docstring, content=symbols);
```

Query API (`src/ract/memory/symbol_index.py`):

- `find_by_name(name, kind_filter=None)`
- `find_by_pattern(regex, kind_filter=None)`
- `find_in_file(path)`
- `find_by_text(query)` via FTS5
- `find_by_hash(content_hash)` for deduplication

Update mechanism: a file watcher (watchdog Python library) triggers a parse-and-diff on save. Only changed symbols get re-indexed. Full rebuild on a 100k-line repo takes seconds on first run; incremental update on save takes milliseconds.

Language coverage in v0.5.0: Python, TypeScript, Rust, Go. Each language has a tree-sitter grammar bundled and a chunking-rule module at `src/ract/memory/languages/<lang>.py`.

### Graph index

SQLite schema at `src/ract/memory/graph_index_schema.sql`:

```sql
CREATE TABLE edges (
  id INTEGER PRIMARY KEY,
  source_symbol_id INTEGER NOT NULL,
  target_symbol_id INTEGER NOT NULL,
  edge_type TEXT NOT NULL,  -- calls, imports, inherits, implements, references
  location_file TEXT,
  location_line INTEGER,
  strength INTEGER DEFAULT 1,
  FOREIGN KEY (source_symbol_id) REFERENCES symbols(id),
  FOREIGN KEY (target_symbol_id) REFERENCES symbols(id)
);

CREATE INDEX idx_edges_source ON edges(source_symbol_id);
CREATE INDEX idx_edges_target ON edges(target_symbol_id);
CREATE INDEX idx_edges_type ON edges(edge_type);
```

Query API (`src/ract/memory/graph_index.py`):

- `callers_of(symbol_id, max_hops=1)`
- `callees_of(symbol_id, max_hops=1)`
- `blast_radius(symbol_id, max_hops=2)`
- `path_between(source_id, target_id)`
- `orphans()` for dead-code candidates
- `hotspots(threshold)` for high-strength edges

Populated from LSP servers via `multilspy`. LSP roundtrip cost is paid once per file change and cached in the graph store; re-query is a local SQL read.

### Semantic index

LanceDB schema at `src/ract/memory/semantic_index.py`. One embedding per AST chunk:

```python
schema = {
  "chunk_id": str,
  "symbol_id": int,       # foreign key to symbols
  "file_path": str,
  "chunk_kind": str,      # function, class, docstring, comment_block
  "signature": str,
  "vector": vector(384),
  "content_hash": str,
  "token_count": int
}
```

Query API:

- `search(query_text, top_k=10, filter=None)`
- `search_by_symbol(symbol_id, top_k=10)` for similarity
- `search_with_budget(query_text, token_budget)` returns what fits

Default embedding model: `bge-small-en-v1.5`. Alternative under config: `nomic-embed-text-v1.5`. Both run locally on CPU or iGPU. Batch rebuild on a 100k-line repo takes minutes on first run; incremental takes seconds.

---

## The retrieve primitive

Formal signature (`src/ract/memory/retrieve.py`):

```python
def retrieve(
    query: RetrievalQuery,
    indexes: list[IndexRef],
    budget: TokenBudget,
    format: ChunkFormat = ChunkFormat.FULL,
    strategy: RetrievalStrategy = RetrievalStrategy.RELEVANCE,
) -> RetrievalBundle: ...
```

```python
class RetrievalQuery:
    symbol_names: list[str] = []
    keywords: list[str] = []
    graph_seeds: list[SymbolRef] = []
    graph_direction: GraphDir = BOTH
    graph_hops: int = 1
    file_scope: list[str] | None = None
    exclude_paths: list[str] = []

class ChunkFormat(Enum):
    FULL = "full"
    BODY_ONLY = "body"
    SIGNATURE = "sig"
    SUMMARY = "summary"

class RetrievalStrategy(Enum):
    RELEVANCE = "relevance"
    COMPREHENSIVE = "complete"
    CORE_FIRST = "core"

class RetrievalBundle:
    chunks: list[Chunk]
    total_tokens: int
    budget_used_pct: float
    dropped_count: int
    dropped_symbols: list[str]
    query_trace: QueryTrace
```

### Retrieval cascade

When a query returns more content than budget allows, `retrieve` cascades through downgrades before dropping content. Cascade never widens; it only shrinks.

1. **Level 1.** FULL for all matches. If under budget, return.
2. **Level 2.** FULL for exact matches; SIGNATURE for keyword and semantic matches.
3. **Level 3.** FULL for exact matches; SIGNATURE for one-hop graph; drop semantic matches.
4. **Level 4.** SIGNATURE for exact matches; drop everything else. Return with `dropped_symbols` populated.
5. **Refuse.** If level 4 still exceeds budget, return empty bundle with `BoundedContextError`, forcing the caller to narrow the query.

Every cascade emits `retrieval.cascaded` to the event trace with the level reached. Every refuse emits `retrieval.refused`.

### Cache layer

Results cache by `(query_hash, repo_commit_hash)`. Cache invalidates on any file change touching returned symbols (the file watcher publishes an invalidation). Storage: SQLite at `.rack/cache/retrieval.db`. Typical hit rate on repeated workflows: 60-80%.

---

## Chunk discipline

### AST chunking rules

Per language, tree-sitter produces the parse tree. RACT applies these rules (per-language module under `src/ract/memory/languages/`):

- **Python.** module, class, function, method, decorator+function group. Docstrings stay attached. Module-level type aliases are their own chunks.
- **TypeScript/JavaScript.** module, class, function, method, arrow function assigned to const at module scope, interface, type. JSDoc stays attached.
- **Rust.** module, struct, enum, trait, impl block, function, method. Doc comments stay attached.
- **Go.** package, struct, interface, function, method. Preceding comments stay attached.

Other languages (Java, Kotlin, C#, C/C++) defer to v0.6.

### Chunk overflow

Some functions are legitimately huge. Two strategies:

1. **Semantic sub-chunking.** Break at logical boundaries: for/while blocks, if/else branches, try/except regions. Each sub-chunk carries its parent function's signature and a locator noting which sub-chunk it is. Reassembly is deterministic.
2. **Summary chunking.** For functions where sub-chunking would still overflow, produce a compressed summary via a local small model dispatched through the existing `providers/` layer. The summary preserves control flow, external calls, and side effects. The original stays in the semantic index for on-demand exact-region retrieval.

### Cross-function grouping

Some symbols are meaningless in isolation. Automatic grouping rules:

- A dataclass and all its methods retrieve together.
- A trait/interface and its implementations retrieve together when the query is about the trait.
- A test function retrieves with its subject function.
- A function retrieves with its type aliases.

Configurable per project through `ract.yaml`.

---

## Function contracts

### intake

**Purpose.** Normalize a user request into a WorkOrder.

**Input.** User request text, repo path, optional context (open file, selected code, current git branch).

**Output.** WorkOrder with `request_type`, `scope_hints`, `success_criteria`, `constraints`, `priority_markers`.

**Budget.** Input target 2k, max 3k. Output target 500. Total ceiling 3k.

**Retrieval.** Recent git log (last 10 commits, summaries only), README top section, any explicitly mentioned files' signatures. No code bodies.

**Test file.** `tests/memory/test_intake.py`.

### research

**Purpose.** Discover relevant scope. Produce a ResearchBundle the plan step can act on.

**Input.** WorkOrder.

**Output.** ResearchBundle with `relevant_symbols` (with per-symbol rationale), `call_neighborhood` (one-hop graph, signatures), `architectural_context`, `similar_prior_work` (commit history matches), `risk_zones`.

**Budget.** Input target 3k, max 4k. Output target 3k. Reasoning headroom 3k. Ceiling 9k.

**Retrieval.** Repo map (compressed TOC), symbol index for explicitly named symbols, FTS on docstrings/comments using WorkOrder keywords, semantic search on WorkOrder text top 10 by signature, graph one-hop neighborhood signatures, git log grep for keywords top 5 commits with diff summaries. Bundle target 3k of metadata and signatures.

**Test file.** `tests/memory/test_research.py`.

### plan

**Purpose.** Convert ResearchBundle into an executable ChangePlan.

**Input.** WorkOrder plus ResearchBundle.

**Output.** ChangePlan with `target_symbols`, `load_manifest`, `invariants` (ast-grep queries or test names), `verification_criteria` (compiled into `AcceptancePredicate` values), `risk_assessment`, `iteration_bound`.

**Budget.** Input target 4k, max 5k. Output target 1k. Reasoning headroom 3k. Ceiling 8k.

**Retrieval.** May issue mid-invocation `retrieve` calls under scoped sub-budgets (500 tokens each, max 3 calls).

**Test file.** `tests/memory/test_plan.py`.

### edit

**Purpose.** Produce a candidate diff implementing the plan.

**Input.** ChangePlan plus resolved `load_manifest`.

**Output.** CandidateDiff in unified diff format with per-hunk summary.

**Budget.** Input target 8k, max 12k. Output target 3k. Reasoning headroom 3k. Ceiling 18k.

**Retrieval.** Load actual code for symbols in `load_manifest`. FULL for modified symbols. BODY_ONLY for called-by-modified. SIGNATURE for wider neighborhood.

**Output discipline for v0.5.0.** AST validation on the produced diff (tree-sitter parse must succeed on the post-patch file), plus retry-on-parse-error up to twice with the parse error as additional context. Grammar-constrained generation (Outlines) defers to v0.6.

**Test file.** `tests/memory/test_edit.py`.

The remaining four functions (`verify`, `review`, `commit`, `document`) defer to v0.6. Their contracts are drafted in `docs/RACT_v0.6_MEMORY_HARDENING_DRAFT.md` (created by module_10 as forward context, not shipped as guidance in v0.5.0).

---

## Playbooks

Each playbook is a YAML at `src/ract/memory/playbooks/`. The playbook names composition (`intake -> research -> plan -> edit`), per-phase retrieval, per-phase budget override.

### Refactor: rename symbol

`intake -> research -> plan -> edit_loop`. Research: symbol index exact match, graph index for all references, grep for string literals. Plan: `load_manifest` per file; if manifest > 5 files, split into multiple edits. Edit loop: one edit per file, budget 6k typical.

### Refactor: extract method

`intake -> research -> plan -> edit`. Research: target function FULL, immediate callers SIGNATURE, containing class/module symbol map. Plan: extraction boundary, new method name, signature, parameters to pass, state to preserve. Edit: single invocation, budget 6k.

### Bug fix

`intake -> research -> reproduce -> plan -> edit`. Research: reported symbol FULL, callers FULL, related test file FULL, git log grep for recent changes to this symbol. Reproduce: deterministic — run reported failing test. Plan: fix hypothesis, specific change, regression test to add. Edit: budget 8k.

### Unit test

`intake -> research -> plan -> edit`. Research: target function FULL, callers SIGNATURE, existing test file FULL if it exists, test framework config. Plan: happy path, edge cases, error cases, boundary conditions. Edit: budget 6k.

---

## Self-adjustment

### Quality probes

Three probe suites, all at `src/ract/memory/probes/`:

- **Needle probe** (`needle.py`). Insert a specific fact at various depths in context of increasing size. Ask a question requiring the fact. Measure recall. Establishes empirical usable context window.
- **Coherence probe** (`coherence.py`). Provide long context with subtle inconsistency. Ask the model to identify it. Establishes reasoning quality at length.
- **Instruction adherence probe** (`adherence.py`). Provide long context with specific instruction at beginning. Ask a question requiring the instruction. Establishes instruction persistence.

Probe results feed a `model_capability` record in `.rack/probes/capability.json`. Budgets derive from this record, not from static defaults, when the record is populated. Default budgets ship as fallback for a fresh install.

### Failure learning

Every function failure emits a structured record. Aggregated over time, patterns emerge. v0.5.0 ships the record shape and the aggregator; the automated nightly narrowing job defers to v0.6.

### Repo fingerprint

Each repo builds a fingerprint over time: average function length, typical import depth, LSP response time distribution, test suite runtime. Fingerprint feeds retrieval defaults per repo. Persistence at `.rack/fingerprint/repo.json`.

---

## Overflow handling

Explicit cascade when retrieval cannot fit required content in budget.

- **Level 1: Format downgrade** (automatic inside `retrieve`).
- **Level 2: Scope narrowing.** Plan re-invoked with request to narrow `load_manifest`. Composition notes the narrowing in the trace.
- **Level 3: Plan splitting.** Plan decomposed into sub-plans, each with its own edit cycle.
- **Level 4: Escalation.** Change genuinely requires more context than any budget allows. Escalate to operator with an explicit explanation of the constraint.

Overflow events emit `retrieval.cascaded` (levels 1-3) or `retrieval.refused` (level 4) to the event trace. Aggregated data feeds self-adjustment.

---

## Sacred spine

The load-bearing invariants no future release can violate. Each has a named test file.

1. **Rootknot's three-signature schema stays intact.** Test: `tests/test_release_surface.py::test_rootknot_signature_count_unchanged` (existing).
2. **The wordlist gate stays green.** Test: `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files` (existing).
3. **Budget hard-ceiling is enforced.** Test: `tests/memory/test_budget_ceiling.py::test_over_ceiling_refuses_invocation_before_model_call`.
4. **Retrieval cascade always terminates.** Test: `tests/memory/test_retrieve_cascade.py::test_cascade_never_loops_returns_or_refuses`.
5. **Retrieval refuse-on-exhaustion emits `retrieval.refused`.** Test: `tests/memory/test_retrieve_cascade.py::test_refuse_emits_event`.
6. **Golden hash gate passes with the new `src/` additions.** Test: `tests/test_release_surface.py::test_golden_hash_matches` (existing; re-locked in module_10).
7. **Rootknot generator payload extension is backward-compatible.** Test: `tests/memory/test_rootknot_retrieval_attestation.py::test_older_sidecar_still_verifies`.
8. **Author-name-free tree stays intact.** Test: `tests/test_release_surface.py::test_no_root_author` (existing).

---

## Signals checklist (final gate before `v0.5.0` tag)

module_10 does not commit the tag until every one of the following is `true`. Each item is a testable file/module/behavior existence check.

1. `src/ract/memory/budget.py` exists; `BudgetAccountant` refuses invocation on ceiling violation.
2. `src/ract/memory/budget_defaults.yaml` exists with a declaration for each of the four v0.5.0 functions.
3. `src/ract/memory/symbol_index.py` exists; SQLite schema at `src/ract/memory/symbol_index_schema.sql`; incremental file watcher lands under `src/ract/memory/watcher.py`.
4. Tree-sitter grammars for Python, TypeScript, Rust, Go are bundled or fetched at install; language chunking rules at `src/ract/memory/languages/{python,typescript,rust,go}.py`.
5. `src/ract/memory/graph_index.py` exists; LSP integration via `multilspy` populates edges; query API includes `blast_radius`.
6. `src/ract/memory/semantic_index.py` exists; LanceDB store at `.rack/index/semantic/`; default embedding is `bge-small-en-v1.5`.
7. `src/ract/memory/retrieve.py` exists; four-level cascade implemented; cache at `.rack/cache/retrieval.db`.
8. `src/ract/memory/functions/{intake,research,plan,edit}.py` all exist; each has a per-function default budget in the registry; each has a paired test file under `tests/memory/`.
9. `src/ract/memory/playbooks/{refactor_rename,refactor_extract,bug_fix,unit_test}.yaml` all exist and load through the composition runner.
10. `src/ract/memory/probes/{needle,coherence,adherence}.py` all exist; `.rack/probes/capability.json` writes on first probe run.
11. Seven new event kinds in `src/ract/trace/events.py::EventKind`: `budget.declared`, `budget.exceeded`, `retrieval.requested`, `retrieval.satisfied`, `retrieval.cascaded`, `retrieval.refused`, `probe.evaluated`.
12. `SubstrateLoop` wires the retrieval bundle into every `SubstrateStepSpec.metadata`; the wiring lives at `src/ract/executor/loop.py` (extended) and is covered by `tests/executor/test_substrate_loop_retrieval_wiring.py`.
13. `Rootknot` generator payload extension carries `retrieval_attestation` optionally; older sidecars verify under compatibility reader; test at `tests/memory/test_rootknot_retrieval_attestation.py`.

---

## Ecosystem drift

Ecosystem versions checked at spec time (2026-08-17):

- **tree-sitter.** Python bindings `tree-sitter` 0.23+. Grammars for Python/TS/Rust/Go all under `tree-sitter-<lang>` PyPI packages. No known breakage on Windows ARM64.
- **multilspy.** Version 0.0.9+ (Microsoft Research). LSP client wraps `pylsp`, `typescript-language-server`, `rust-analyzer`, `gopls`. Each LSP server is a separate install; the module_03 install script documents each. Windows ARM64 support: `pylsp` and `typescript-language-server` yes; `rust-analyzer` and `gopls` yes; if a specific LSP is missing, graph index degrades to symbol-only for that language.
- **LanceDB.** Version 0.15+. Windows ARM64 wheel: verify at install time; fallback to CPU-only mode if the GPU accel wheel is absent.
- **bge-small-en-v1.5.** Hugging Face model, 384-dim, MIT license, CPU-friendly.
- **nomic-embed-text-v1.5.** Hugging Face, 768-dim, Apache-2.0. Alternative under config.
- **DSPy.** Deferred to v0.6. Reason: DSPy's compile pass is nightly infrastructure, not per-step; v0.5.0 ships the substrate DSPy sits on but does not ship DSPy itself.
- **Outlines.** Deferred to v0.6. Reason: grammar-constrained generation is `edit`'s output discipline; v0.5.0 uses AST validation + retry-on-parse-error as the stopgap.

**Risk flags:**

- multilspy is a research project. Its API is not stable across minor versions. Module_03 pins the version and treats the pin as a load-bearing dependency; a version bump requires an ADR.
- LanceDB's Windows ARM64 wheel is not always current. Module_04 documents the CPU-only fallback and gates the install on wheel availability.
- Tree-sitter grammars occasionally rev their AST shape (e.g., TypeScript grammar 0.20 vs 0.21 renamed several node kinds). Module_02's chunking-rule modules pin the grammar version per language.

---

## Bar policy

Same shape as v0.4.1, one turn tighter.

- **DoD is the floor.** Each module's Definition of Done is a boolean checklist. When it passes, the module commits.
- **Log Flagged gaps at close.** After the DoD-met commit, the module author fills in the `Flagged gaps (to log at close)` section with what "excellent" would have demanded past the DoD. That log is the input to v0.6 hardening; it is never silently dropped.
- **v0.5 raises the bar past v0.4.1.** DoDs in this pipeline embed the 13 §Signals as boolean tests. No module whose DoD would have passed in v0.4.1; the bar has moved.
- **DoDs are pre-signed by the pipeline, not renegotiated in-module.** A module that finds its DoD infeasible halts, surfaces the reason to the operator, and does not lower the DoD.

---

## Cadence and watchdog

- **Cadence.** Per-sub-task. Each step within a module externalizes state to `build_state.md` before advancing.
- **Watchdog.** Cron. The main session registers the cron id at kickoff and logs it in the ledger's Status log. The resume pulse reads `active_module` from the frontmatter and continues at that module's first not-yet-DONE step.
- **Advance rule.** The resume pulse never invents a new module. If `active_module` is `module_04.md` and step 3 is not yet DONE, the pulse resumes at step 3 of module_04.
- **Halt-and-file rule.** Any module that cannot meet its DoD halts, files a note to the ledger, and yields.

---

## Reference implementation notes

### Repository layout (additions)

```
src/ract/memory/
  __init__.py
  budget.py                # BudgetAccountant, BudgetDeclaration
  budget_defaults.yaml     # per-function default budgets
  symbol_index.py
  symbol_index_schema.sql
  graph_index.py
  graph_index_schema.sql
  semantic_index.py
  retrieve.py
  chunk.py
  cache.py
  watcher.py
  languages/
    __init__.py
    python.py
    typescript.py
    rust.py
    go.py
  functions/
    __init__.py
    intake.py
    research.py
    plan.py
    edit.py
  playbooks/
    refactor_rename.yaml
    refactor_extract.yaml
    bug_fix.yaml
    unit_test.yaml
  probes/
    __init__.py
    needle.py
    coherence.py
    adherence.py
    scheduler.py
  prompts/
    intake_v1.md
    research_v1.md
    plan_v1.md
    edit_v1.md

tests/memory/
  test_budget.py
  test_budget_ceiling.py
  test_symbol_index.py
  test_graph_index.py
  test_semantic_index.py
  test_retrieve.py
  test_retrieve_cascade.py
  test_chunk.py
  test_watcher.py
  test_intake.py
  test_research.py
  test_plan.py
  test_edit.py
  test_playbook_refactor_rename.py
  test_playbook_refactor_extract.py
  test_playbook_bug_fix.py
  test_playbook_unit_test.py
  test_probes.py
  test_rootknot_retrieval_attestation.py

tests/executor/
  test_substrate_loop_retrieval_wiring.py
```

### External dependencies (additions)

Hard runtime:

- `tree-sitter` >= 0.23
- `tree-sitter-python`, `tree-sitter-typescript`, `tree-sitter-rust`, `tree-sitter-go`
- `multilspy` (pinned per module_03 ADR)
- `lancedb` >= 0.15
- `watchdog` (Python file-watcher library)

Local model (bundled or first-run download):

- `bge-small-en-v1.5` (default embedding)
- `nomic-embed-text-v1.5` (alternative under config)

Deferred to v0.6:

- `dspy`
- `outlines`

Runtime: whichever inference server RACT already uses via the existing `providers/` layer.

### Bootstrapping a new repo

First-run pipeline (all under `ract memory init`):

1. Full walk to build symbol index (tree-sitter parse every file).
2. Full walk to build graph index (LSP query every file, cache results).
3. Full walk to build semantic index (embed every chunk).
4. Compute repo map (compressed TOC).
5. Register file watcher for incremental updates.
6. Run initial probe suite to establish `model_capability` baseline.

Elapsed time on 100k-line repo: minutes on first run, sub-second per file change after.

### Testing the harness

Test coverage:

- Every function's contract (input validation, output validation) — one test file per function.
- Every retrieval strategy against a fixture repo.
- Every playbook against a fixture workflow.
- Overflow handling at every cascade level.
- Self-adjustment probes against known-good and known-degraded model states (mocked provider).
- Rootknot backward compatibility across v1/v2/v3 sidecars plus the new `retrieval_attestation` field.

Fixture repo: `tests/memory/fixtures/tiny_repo/` — a stripped-down multi-language codebase (Python + TypeScript + Rust + Go) with tests, docs, and typical churn patterns. Used as ground truth by every retrieval and playbook test.

---

## Closing note

Memory discipline is the substrate that makes the four gates v0.4.x shipped meaningful in practice. G1 held-out predicates catch a `edit` that games the visible suite; G2 mutation-kill catches an `edit` that ships thin tests; G6 under-edit closure catches an `edit` that names files outside the loaded neighborhood; G7 companion catches a single-pass `edit` that skipped context. Every one of those gates presumes the `edit` step assembled its context under a declared budget with an inspectable retrieval bundle. v0.5.0 lands that presumption as a fact.

The self-adjustment layer is what makes it durable. A provider update, a repo growth event, a new language added, a degrading LSP: none of these require re-speccing. The probes measure, the failure records aggregate, the budgets narrow. The harness converges toward correct behavior on the actual provider it runs on, not on an assumed one.

v0.6 hardens what v0.5.0 ships. v0.5.0 does not ship a demo; it ships a substrate.
