# ADR-0032 — Symbol index as SQLite + tree-sitter + FTS5

Status: accepted (v0.5.0 Memory Discipline, module_02).

## Context

The memory-discipline pipeline needs a first-order lookup that keys
the other two indexes (graph + semantic). Symbol lookup is the
atomic operation the retrieve primitive (module_05) composes over:
every ``research`` and ``plan`` step reads the symbol index dozens
of times per model call. The lookup shape must support at minimum
exact-name lookup, regex pattern match, per-file listing, docstring
+ name full-text search, and content-hash dedup.

The v0.2-era ``src/ract/symbol_graph.py`` shipped a Python-only
AST-import lookup keyed on module name. It is preserved (module_09
migrates its first call site — the planner's symbol resolution) but
does not compose with the memory-discipline pipeline's
polyglot requirement (Python + TypeScript + Rust + Go) or its
docstring-FTS requirement.

The load-bearing question is the store shape and the parser
technology. Four alternatives were considered.

## Alternatives considered

**1. Pure AST-import (v0.2 predecessor).** Refused because:

- Python-only. TypeScript / Rust / Go are outside the reach of
  Python's ``ast`` module.
- No FTS. Docstring search would degrade to ``in`` string matching
  over an in-memory dict, which is O(N) per query against a repo
  that ships tens of thousands of symbols.
- No content-hash dedup surface. The retrieve primitive's cache
  layer (module_05) needs a stable hash per symbol to invalidate on
  file change; hashing at read time defeats the point.

**2. ctags (external process).** Refused because:

- Per-language config drift. Universal Ctags supports many
  languages but the per-language definition files diverge across
  versions and platforms; a Windows-ARM64 install ships with a
  different default set than a Linux install.
- External process cost. Every incremental update spawns a
  subprocess. The debounced watcher path (module_02's watcher runs
  parse-and-diff on save; see ``src/ract/memory/watcher.py``) would
  amortise poorly against a 30 ms process spawn per file.
- No structured docstring extraction. Ctags emits identifier +
  location; docstring/JSDoc/Rustdoc go missing.

**3. LSP-only lookup (multilspy).** Refused because:

- LSP is a per-file per-position protocol, not a whole-repo index.
  A symbol search across a repo becomes a workspace/symbol call
  that most LSP servers handle at O(N) internally.
- Wrong axis. multilspy is the right tool for the graph index
  (module_03) because callers/callees/blast-radius all live in the
  LSP's cross-reference view; it is the wrong tool for symbol
  lookup because it does not carry docstring FTS or content-hash
  dedup as first-class fields.
- Boot cost. Starting a per-language LSP server just to look up a
  symbol name is a load-bearing cost on cold start; the SQLite
  store is available the instant the file opens.

**4. In-memory dict keyed on name (accepted for module_01
scratchpad, refused for module_02).** Refused for the module_02
production surface because:

- No FTS. A dict from name to symbol list handles exact-name lookup
  but not docstring search.
- No persistence. A restart re-parses every file; SQLite persists.
- No cross-process readers. A future integration where a second
  RACT process (test runner, watcher, IDE plugin) reads the index
  would need to duplicate the parser.

**5. SQLite + tree-sitter + FTS5 (accepted).** SQLite ships with
Python 3.11+ and (on the standard Windows / Linux builds) with FTS5
compiled in; a defensive PRAGMA compile-options check raises
:class:`SqliteMissingFTS5Error` on the rare build that lacks FTS5
(historically macOS system Python). Tree-sitter is the
industry-standard parser toolchain, ships PyPI wheels for
Python / TypeScript / Rust / Go on Windows ARM64, and produces a
compact incremental parse that matches the module_02 watcher's
per-file update path.

The FTS5 virtual table uses ``content=symbols content_rowid=id`` so
the index mirrors the source rows without duplicating storage.
Three triggers (``symbols_ai``, ``symbols_ad``, ``symbols_au``)
keep the FTS mirror consistent within the same transaction as the
source-row write (Second Pass Q4: a query issued after
``insert_or_update`` never hits a stale FTS snapshot).

## Decision

The symbol index is a SQLite store at ``.rack/index/symbols.db``
with the schema at ``src/ract/memory/symbol_index_schema.sql``. The
parser layer is tree-sitter, dispatched by extension through
``src/ract/memory/parser.py`` to a per-language module at
``src/ract/memory/languages/<lang>.py``. The FTS5 mirror lives in
the same store, kept consistent via triggers.

Each per-language module pins its ``tree-sitter-<lang>`` grammar
version explicitly (Lateral Chain branch A) and raises
:class:`~ract.memory.languages.GrammarVersionMismatchError` at
import when the installed version drifts. The pin is a load-bearing
choice: tree-sitter grammars occasionally rev their AST node kinds
(TypeScript 0.20 vs 0.21 renamed several node kinds). Without the
pin, a grammar upgrade would silently produce an empty symbol
list against the old chunking rules.

The file watcher at ``src/ract/memory/watcher.py`` runs two
independent invalidation paths side by side:

- A ``watchdog`` :class:`Observer` streams create / modify /
  delete / move events. A per-path debouncer (default 100 ms
  window) batches the save floods editors emit and re-parses the
  file once.
- A periodic-scan thread compares filesystem ``mtime`` against the
  ``symbols.updated_at`` recorded per file and re-indexes any file
  whose ``mtime`` is newer. This closes the missed-save worry on
  Windows (Lateral Chain branch B); the periodic thread is a
  daemon distinct from the debouncer so a slow parse cannot block
  the fallback (Second Pass Q3).

The walker at ``src/ract/memory/walker.py`` respects ``.gitignore``
+ ``.ractignore`` via ``pathspec`` (Lateral Chain branch C: binary
files and generated code do not swamp the index).

Query API is language-agnostic (Lateral Chain branch E):
``SymbolRow.language`` is a filter, not a partition;
``find_by_name("User")`` returns the Python ``User`` class and the
TypeScript ``User`` type in one result set. This composes with the
retrieve primitive's cross-language cascade.

## Consequences

Positive:

- polyglot lookup with one store and one API shape;
- FTS docstring search on a tens-of-thousands-of-symbols repo runs
  in milliseconds;
- incremental updates on file save land inside the debounce window
  (defaults to 100 ms), so the index is fresh by the time the next
  model call assembles its context;
- the periodic-scan fallback guarantees eventual consistency even
  when the watchdog event stream drops events;
- ``.gitignore`` and ``.ractignore`` filter the walk so a
  ``frontend/dist/`` bundle does not swamp the index.

Negative / deferred:

- parent linkage (``parent_symbol_id``) is NULL for module_02
  because the module_02 parser walks each file in isolation; the
  module_03 graph index will populate containment edges from LSP
  workspace/symbol data. Logged as a Flagged gap.
- language coverage limited to Python / TypeScript / Rust / Go
  in v0.5.0; Java / Kotlin / C# / C/C++ defer to v0.6.
- semantic sub-chunking (spec §Chunk overflow) is not yet
  implemented — large functions land as a single chunk. Logged as
  a Flagged gap.
- the whitespace-based ``token_count`` estimator inherits ADR-0031's
  BPE-under-count caveat (20-40 percent low against provider
  tokenizers). Module_09 wires per-provider estimators.

Reference: docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md
§The three indexes / Symbol index, §Signals items 3-4.
