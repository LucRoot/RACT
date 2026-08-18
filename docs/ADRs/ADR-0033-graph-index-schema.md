# ADR-0033 — Graph index via SQLite cache + multilspy LSP driver

Status: accepted (v0.5.0 Memory Discipline, module_03).

## Context

The memory-discipline pipeline needs a call/import/inheritance
graph that composes with the module_02 symbol index. Every
``research`` step and every ``plan`` step reads the graph to
compute a callable neighborhood; every ``edit`` step reads the
graph for blast-radius against a proposed change site. Without
this module the retrieve primitive (module_05) cannot produce
``call_neighborhood`` and ``plan``'s ``load_manifest`` cannot
compute blast-radius for its ``risk_assessment``.

The v0.2-era ``src/ract/dependency_graph.py`` shipped a
Python-only AST-import graph keyed on module name. It is
preserved (module_09 migrates its first call site) but does not
compose with the memory-discipline pipeline's polyglot
requirement (Python + TypeScript + Rust + Go) or its edge-type
vocabulary (calls / imports / inherits / implements /
references).

The load-bearing question is the edge source: how does the
populator recognise a callers/callees relationship across four
languages? Four alternatives were considered.

## Alternatives considered

**1. Pure AST-import (v0.2 predecessor).** Refused because:

- Python-only. TypeScript / Rust / Go carry their own call and
  reference semantics (method resolution order, trait dispatch,
  interface implementation) that Python's ``ast`` module cannot
  see.
- Module-level only. The v0.2 graph keys on module name; the
  memory-discipline graph keys on symbol id (function, method,
  class member) so the retrieve primitive can produce a callable
  neighborhood, not just a file list.

**2. Per-language custom parsers (drift).** Refused because:

- Every language needs its own reference resolver. Python name
  resolution alone is a substantial project (LEGB, dynamic
  attribute lookup, ``__getattr__``); TypeScript adds module
  augmentation and declaration merging; Rust adds trait
  resolution across the entire crate graph. A pass built inside
  RACT would drift from every language's real toolchain within
  months.
- No cross-file guarantee. A per-language custom parser sees
  one file at a time; a caller in ``a.py`` referring to a
  callee in ``b.py`` requires the parser to resolve the import,
  which drags in the full name-resolution problem.

**3. Single global LSP.** Refused because there is no such
thing. Every real LSP is per-language; multilspy is a Python
wrapper that dispatches by language to the appropriate server.
A "single global LSP" would be a fiction — a Python layer that
still starts one subprocess per language. The right design
names the reality (one server per language) and pins the
lifetime + concurrency model.

**4. multilspy per language + SQLite cache (accepted).**
multilspy wraps four production-grade language servers
(``jedi-language-server`` / ``typescript-language-server`` /
``rust-analyzer`` / ``gopls``) behind a uniform Python API.
Each server is the ground-truth reference resolver for its
language. LSP roundtrip cost is paid once per file change and
cached in a SQLite ``edges`` table; re-query is a local SQL
read at millisecond latency.

## Decision

The graph index is a SQLite store at ``.rack/index/graph.db``
with the schema at ``src/ract/memory/graph_index_schema.sql``.
The populator layer is multilspy, wrapped through
``src/ract/memory/lsp.py``, and drives the store through
``src/ract/memory/graph_populator.py``. The fallback path at
``src/ract/memory/lsp_fallback.py`` populates self-referential
edges marked ``neighborhood_source='symbol_only'`` when the LSP
for a language is unavailable so downstream retrieval can
distinguish "no neighborhood" from a real callback loop.

Every edge references ``symbols.id`` from the module_02 store.
The two stores live in separate SQLite databases at production
time (``graph.db`` vs ``symbols.db``); foreign keys are not
declared at the schema level. Referential integrity is
maintained by the populator's source-file-scoped delete + re-
insert path (``GraphIndex.delete_by_source_file`` +
``GraphIndex.insert_edges`` inside a single transaction).

Constraints inherited from the module_02 POST-audit chain:

- **Chunker-parity constraint** (module_02 POST-A). The LSP
  language set (``LSP_ADAPTERS``) is a strict subset of the
  languages module_02 parses. Adding a language to
  ``LSP_ADAPTERS`` without a matching parser under
  ``src/ract/memory/languages/`` would populate the graph with
  edges pointing at symbol ids that do not exist. A test in
  ``test_graph_index_lsp.py`` binds ``LSP_ADAPTERS`` to
  ``{python, typescript, rust, go}``.

- **Import-alias resolver** (module_02 POST-E). The graph
  populator's caller-side resolver is
  ``GraphPopulator._global_resolver`` (formerly
  ``_resolver_for_file``); it maps an LSP-reported ``(path,
  line)`` back to a ``symbols.id`` by containment check rather
  than by name-string. An aliased import
  (``from foo import Bar as _b``) resolves the caller's symbol
  correctly because the resolver reads the caller's file +
  line, not the alias name at the reference site.

- **No competing FTS5 layer** (module_02 POST-C corollary).
  Module_02 already ships an FTS5 virtual table over the
  ``symbols`` content. The graph index does NOT build a parallel
  FTS5 index; edge-text queries JOIN
  ``symbols_fts.rowid = symbols.id`` through module_02.
  Edge-side queries (callers / callees / blast_radius /
  hotspots) do not need FTS5 at all.

## multilspy pin

The multilspy API is not stable across minor versions (Lateral
Chain branch A). The ``pyproject.toml`` pin is
``multilspy>=0.0.15,<0.1``; a version bump requires a fresh
ADR. The wrapper at ``src/ract/memory/lsp.py`` imports through
``_load_multilspy`` so a caller who only uses the fallback path
does not pay the multilspy import cost.

## Concurrency + lifetime

Per Lateral Chain branch C, each language server is a
heavyweight subprocess (``rust-analyzer`` and ``gopls`` both
take seconds to start). :class:`~ract.memory.lsp.LspClient`
keeps one server alive per language for the lifetime of the
:class:`~ract.memory.graph_populator.GraphPopulator`; the
populator's context manager ensures shutdown on close.

The initial-build path batches by file (one LSP ``open_file``
per source file, not per symbol) so a 100k-line repo pays
O(files) LSP roundtrips rather than O(symbols). Batching is a
Lateral Chain branch B decision.

## Consequences

Positive:

- polyglot call-graph with one API shape across four languages;
- LSP is the ground-truth reference resolver, not a bespoke
  parser RACT would have to maintain;
- LSP roundtrip cost paid once per file change; re-query is a
  local SQL read;
- fallback to symbol-only mode keeps downstream retrieval
  functioning when an LSP is missing, without silently
  claiming callback loops.

Negative / deferred:

- rust-analyzer and gopls are heavyweight processes on start-
  up; the populator amortises this by keeping servers alive but
  the first initial-build on a fresh checkout still pays the
  boot cost.
- cross-language edges (a Python service calling a TypeScript
  worker via HTTP) are invisible to LSP; the master spec scopes
  the graph index to language-internal calls (Lateral Chain
  branch D deferred to v0.6).
- ``jedi-language-server`` (multilspy's default for Python)
  requires read access to the repo root; a permission failure
  on the root path surfaces as an LSP error and triggers
  fallback for that language.

## Rejected alternatives (summary)

| Alternative | Why refused |
|---|---|
| Pure AST-import (v0.2 predecessor) | Python-only; module-level keys only. |
| Per-language custom parsers | Drift from real toolchains; no cross-file resolver. |
| Single global LSP | Not a real thing; every LSP is per-language. |

## Reference

- ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The three
  indexes / Graph index, §Signals item 5.
- multilspy repository: ``https://github.com/microsoft/multilspy``.
- LSP specification: ``https://microsoft.github.io/language-server-protocol/``.
