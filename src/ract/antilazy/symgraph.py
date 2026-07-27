"""ALM Gate G6 — symbol graph + under-edit closure.

ALM spec §3.6. When a symbol is renamed, moved, or has its signature
changed, callers must be updated in the same transaction — or covered
by a test that still passes, or explicitly declared unaffected in the
acceptance suite. Under-editing is the mirror image of test-hacking:
the diff shipped less than the intent required, and the caller
silently references the stale name.

The graph is built with Python's standard-library ``ast`` module and
cached in a per-workspace SQLite database keyed by snapshot digest
(lateral chain branch B): a rebuild only fires when the digest
changes, which keeps loop-entry cost bounded on large workspaces.

Extension points for TypeScript, Go, and Rust are declared and
stub-implemented (log-only) so the graph is at least populated with
Python coverage on mixed-language workspaces (lateral chain branch D
from testintegrity.py).

Design decision (v0.4.0-rc1 ALM module_03): the plan named
tree-sitter as the parser but Python-only coverage is what the DoD
requires and tree-sitter would add a runtime dependency for zero
extra coverage in this scope. The stdlib ``ast`` module handles every
Python symbol shape we need to reason about. A tree-sitter migration
would be a separate ADR when the v0.5 language-expansion pipeline
actually needs the wider grammar surface. See ADR-0021 rejected
alternatives.

Reference sources:

- Python ``ast`` module (public standard-library documentation).
- ``git`` ``.gitattributes`` ``linguist-generated=true`` idiom for
  the generated-file exclusion (lateral chain branch C).
- ALM spec §3.6 (Gate G6); §13 signal 6.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Literal

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


SymbolKind = Literal["function", "class", "method", "import_alias"]


# Reviewer-facing heuristic defaults for the generated-file exclusion
# (Second Pass adversarial question 4). When ``.gitattributes`` is
# absent the graph still excludes these well-known generator outputs
# so absent annotations do not become a false-positive surface.
DEFAULT_GENERATED_HEURISTIC_GLOBS: tuple[str, ...] = (
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*_pb2.pyi",
    "*_pb2_grpc.pyi",
    "*.g.dart",  # dart codegen (irrelevant to Python but harmless)
    "*.freezed.dart",
    "**/generated/**",
    "**/gen/**",
    "**/_generated_*.py",
)


# ---------------------------------------------------------------------------
# Graph value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolNode:
    """One symbol in the workspace's symbol graph."""

    qualified_name: str
    source_file: str
    start_line: int
    end_line: int
    kind: SymbolKind


@dataclass(frozen=True)
class CallEdge:
    """An observed function-call edge between two qualified names."""

    caller: str
    callee: str
    source_file: str
    line: int


@dataclass(frozen=True)
class ImportEdge:
    """An import edge — one module (or ``from`` clause) referencing a symbol."""

    importer: str
    imported_name: str
    source_file: str
    line: int


@dataclass(frozen=True)
class SymbolGraph:
    """Immutable snapshot of the workspace's symbol structure."""

    symbols: dict[str, SymbolNode] = field(default_factory=dict)
    call_edges: tuple[CallEdge, ...] = field(default_factory=tuple)
    import_edges: tuple[ImportEdge, ...] = field(default_factory=tuple)
    unsupported_files: tuple[str, ...] = field(default_factory=tuple)
    generated_files: tuple[str, ...] = field(default_factory=tuple)
    snapshot_digest: str = ""


# ---------------------------------------------------------------------------
# Snapshot digest — cache key for build_graph
# ---------------------------------------------------------------------------


def snapshot_digest_of(snapshot: "WorkspaceSnapshot") -> str:
    """Return a stable SHA-256 hex digest over ``snapshot.files``.

    Digest form: JSON, sorted keys, no whitespace, UTF-8. Any change
    to a file's contents (or the file set) produces a fresh digest,
    which is the cache-invalidation signal for ``build_graph``.
    """
    payload = json.dumps(
        {"files": snapshot.files}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Generated-file discovery
# ---------------------------------------------------------------------------


def _generated_globs_from_gitattributes(text: str | None) -> list[str]:
    """Parse a ``.gitattributes`` string and return globs marked generated."""
    if not text:
        return []
    globs: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        attrs = parts[1:]
        for attr in attrs:
            if attr in {"linguist-generated=true", "linguist-generated"}:
                globs.append(pattern)
                break
    return globs


def _discover_generated_files(snapshot: "WorkspaceSnapshot") -> tuple[str, ...]:
    """Return the files the graph excludes from under-edit closure.

    Sources: ``.gitattributes`` linguist-generated entries plus a set
    of per-language heuristic defaults (Second Pass Q4 default) so
    absent annotations do not silently produce false positives.
    """
    text = snapshot.files.get(".gitattributes")
    author_globs = _generated_globs_from_gitattributes(text)
    all_globs = list(author_globs) + list(DEFAULT_GENERATED_HEURISTIC_GLOBS)
    generated: list[str] = []
    for path in snapshot.files:
        for glob in all_globs:
            if fnmatch.fnmatchcase(path, glob) or fnmatch.fnmatchcase(
                path.replace("\\", "/"), glob
            ):
                generated.append(path)
                break
    return tuple(sorted(set(generated)))


# ---------------------------------------------------------------------------
# Python AST walk
# ---------------------------------------------------------------------------


def _module_name_for(path: str) -> str:
    """Return a dotted module name for a Python file path."""
    p = path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".")


def _parse_python_module(
    path: str, source: str, generated: set[str]
) -> tuple[
    dict[str, SymbolNode], list[CallEdge], list[ImportEdge], bool
]:
    """Parse one Python module. Returns (symbols, calls, imports, is_generated)."""
    if path in generated:
        return {}, [], [], True
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {}, [], [], False
    module_name = _module_name_for(path)
    symbols: dict[str, SymbolNode] = {}
    calls: list[CallEdge] = []
    imports: list[ImportEdge] = []

    class _Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self._scope: list[str] = [module_name]

        def _q(self, name: str) -> str:
            return ".".join(self._scope + [name])

        def _enter(self, name: str) -> None:
            self._scope.append(name)

        def _leave(self) -> None:
            self._scope.pop()

        def _end_line(self, node: ast.AST) -> int:
            end = getattr(node, "end_lineno", None)
            if end is None:
                return getattr(node, "lineno", 0)
            return end

        def visit_FunctionDef(  # noqa: N802
            self, node: ast.FunctionDef
        ) -> None:
            qname = self._q(node.name)
            kind: SymbolKind = "method" if len(self._scope) > 1 else "function"
            symbols[qname] = SymbolNode(
                qualified_name=qname,
                source_file=path,
                start_line=node.lineno,
                end_line=self._end_line(node),
                kind=kind,
            )
            self._enter(node.name)
            self._visit_body(node)
            self._leave()

        def visit_AsyncFunctionDef(  # noqa: N802
            self, node: ast.AsyncFunctionDef
        ) -> None:
            self.visit_FunctionDef(node)  # type: ignore[arg-type]

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            qname = self._q(node.name)
            symbols[qname] = SymbolNode(
                qualified_name=qname,
                source_file=path,
                start_line=node.lineno,
                end_line=self._end_line(node),
                kind="class",
            )
            self._enter(node.name)
            self._visit_body(node)
            self._leave()

        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            for alias in node.names:
                imports.append(
                    ImportEdge(
                        importer=self._q("<module>"),
                        imported_name=alias.name,
                        source_file=path,
                        line=node.lineno,
                    )
                )

        def visit_ImportFrom(  # noqa: N802
            self, node: ast.ImportFrom
        ) -> None:
            base = node.module or ""
            for alias in node.names:
                qname = f"{base}.{alias.name}" if base else alias.name
                imports.append(
                    ImportEdge(
                        importer=self._q("<module>"),
                        imported_name=qname,
                        source_file=path,
                        line=node.lineno,
                    )
                )

        def _visit_body(self, node: ast.AST) -> None:
            # Visit the body of a function/class so nested defs and
            # calls are recorded under the current scope.
            for sub in ast.iter_child_nodes(node):
                self.visit(sub)

        def generic_visit(self, node: ast.AST) -> None:
            # Record calls at every scope level. We do NOT recurse into
            # FunctionDef / ClassDef here — those have their own visit
            # methods that push/pop the scope stack.
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                return
            if isinstance(node, ast.Call):
                call_target = _call_target_name(node.func)
                if call_target:
                    caller_q = (
                        ".".join(self._scope)
                        if len(self._scope) > 1
                        else module_name
                    )
                    calls.append(
                        CallEdge(
                            caller=caller_q,
                            callee=call_target,
                            source_file=path,
                            line=getattr(node, "lineno", 0),
                        )
                    )
                # ``getattr(module, "name")`` is not a normal call site;
                # tree-sitter would not see it either. We surface it as
                # a synthetic call edge with a marker prefix so the
                # closure can escalate on the Q2 gap.
                if (
                    call_target == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Name):
                        caller_q = (
                            ".".join(self._scope)
                            if len(self._scope) > 1
                            else module_name
                        )
                        calls.append(
                            CallEdge(
                                caller=caller_q,
                                callee=(
                                    f"getattr:{first_arg.id}."
                                    f"{node.args[1].value}"
                                ),
                                source_file=path,
                                line=getattr(node, "lineno", 0),
                            )
                        )
            super().generic_visit(node)

    _Walk().visit(tree)
    return symbols, calls, imports, False


def _call_target_name(func: ast.expr) -> str:
    """Return a best-effort dotted name for a call target."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        cur: ast.expr = func.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


# ---------------------------------------------------------------------------
# build_graph — public entry
# ---------------------------------------------------------------------------


def build_graph(
    workspace: "WorkspaceSnapshot",
    *,
    cache_db: Path | None = None,
) -> SymbolGraph:
    """Return a ``SymbolGraph`` for ``workspace``.

    When ``cache_db`` is supplied, the graph is memoized by workspace
    snapshot digest: a fresh call with an unchanged workspace loads
    from SQLite instead of re-parsing every module (lateral chain
    branch B).
    """
    digest = snapshot_digest_of(workspace)
    if cache_db is not None and cache_db.exists():
        cached = load_graph(cache_db, digest)
        if cached is not None:
            return cached

    generated = _discover_generated_files(workspace)
    generated_set = set(generated)
    symbols: dict[str, SymbolNode] = {}
    all_calls: list[CallEdge] = []
    all_imports: list[ImportEdge] = []
    unsupported: list[str] = []

    for path in sorted(workspace.files):
        if not path.endswith(".py") and not (
            path.endswith(".ts")
            or path.endswith(".tsx")
            or path.endswith(".js")
            or path.endswith(".jsx")
            or path.endswith(".go")
            or path.endswith(".rs")
        ):
            continue
        if path.endswith(".py"):
            source = workspace.files.get(path, "")
            file_symbols, file_calls, file_imports, was_gen = _parse_python_module(
                path, source, generated_set
            )
            if was_gen:
                continue
            symbols.update(file_symbols)
            all_calls.extend(file_calls)
            all_imports.extend(file_imports)
        else:
            unsupported.append(path)

    graph = SymbolGraph(
        symbols=symbols,
        call_edges=tuple(all_calls),
        import_edges=tuple(all_imports),
        unsupported_files=tuple(sorted(unsupported)),
        generated_files=generated,
        snapshot_digest=digest,
    )
    if cache_db is not None:
        persist_graph(graph, cache_db)
    return graph


# ---------------------------------------------------------------------------
# Symbol closure and under-edit report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnderEditReport:
    """G6 result — closure of edited symbols with coverage classification."""

    modified_symbols: tuple[str, ...]
    downstream_callers: tuple[str, ...]
    covered_by_test: tuple[str, ...]
    covered_by_edit: tuple[str, ...]
    covered_by_declaration: tuple[str, ...]
    uncovered: tuple[str, ...]
    generated_excluded: tuple[str, ...] = field(default_factory=tuple)
    getattr_advisories: tuple[str, ...] = field(default_factory=tuple)

    def passed(self) -> bool:
        return not self.uncovered

    def to_canonical(self) -> dict[str, object]:
        return {
            "modified_symbols": list(self.modified_symbols),
            "downstream_callers": list(self.downstream_callers),
            "covered_by_test": list(self.covered_by_test),
            "covered_by_edit": list(self.covered_by_edit),
            "covered_by_declaration": list(self.covered_by_declaration),
            "uncovered": list(self.uncovered),
            "generated_excluded": list(self.generated_excluded),
            "getattr_advisories": list(self.getattr_advisories),
        }


def _short_name(qname: str) -> str:
    return qname.rsplit(".", 1)[-1]


def _callers_of(graph: SymbolGraph, symbol: str) -> list[CallEdge]:
    """Return the call edges whose callee matches ``symbol`` (by short name)."""
    short = _short_name(symbol)
    matches: list[CallEdge] = []
    for edge in graph.call_edges:
        callee_short = _short_name(edge.callee)
        if callee_short == short and not edge.callee.startswith("getattr:"):
            matches.append(edge)
    return matches


def _getattr_advisories_for(
    graph: SymbolGraph, edited_symbols: Iterable[str]
) -> list[str]:
    """Return getattr-based references to any edited symbol (Second Pass Q2).

    Tree-sitter (and stdlib ``ast``) will not see a
    ``getattr(module, "old_name")`` as a normal call site. The
    Cycle-2 tree walker records these as synthetic edges with a
    ``getattr:`` prefix so the closure can surface them as an
    advisory rather than a silent hole.
    """
    edited_short = {_short_name(s) for s in edited_symbols}
    hits: list[str] = []
    for edge in graph.call_edges:
        if not edge.callee.startswith("getattr:"):
            continue
        target = edge.callee[len("getattr:") :]
        # target shape: "module_alias.name"
        parts = target.rsplit(".", 1)
        if len(parts) == 2 and parts[1] in edited_short:
            hits.append(f"{edge.source_file}:{edge.line}:{target}")
    return hits


def compute_closure(
    graph: SymbolGraph,
    edited_symbols: Iterable[str],
    *,
    edited_files: Iterable[str] = (),
    passing_tests_touched: Iterable[str] = (),
    declared_unaffected: Iterable[str] = (),
) -> UnderEditReport:
    """Return the ``UnderEditReport`` for a step's edits.

    ``edited_symbols`` names the qualified symbols the step modified.
    ``edited_files`` names the file paths touched (so a caller that
    lives in the same file is covered by edit even if we could not
    map it precisely). ``passing_tests_touched`` lists qualified names
    of test functions that were exercised (and passed). ``declared_
    unaffected`` names symbols the acceptance suite explicitly marked
    unaffected — the branch that lets an operator override the
    closure without editing every call site.
    """
    edited_set = set(edited_symbols)
    edited_files_set = set(edited_files)
    passing_tests_set = set(passing_tests_touched)
    declared_set = set(declared_unaffected)

    downstream: dict[str, CallEdge] = {}
    for symbol in edited_set:
        for edge in _callers_of(graph, symbol):
            # Only surface callers that are NOT themselves the edited
            # symbol (a self-recursive call does not need a separate
            # update). Keyed by caller qualified name so duplicates
            # collapse.
            if edge.caller in edited_set:
                continue
            downstream[edge.caller] = edge

    generated_excluded: list[str] = []
    for caller, edge in list(downstream.items()):
        if edge.source_file in graph.generated_files:
            generated_excluded.append(caller)
            downstream.pop(caller, None)

    covered_by_test: list[str] = []
    covered_by_edit: list[str] = []
    covered_by_declaration: list[str] = []
    uncovered: list[str] = []

    for caller, edge in downstream.items():
        if caller in declared_set or _short_name(caller) in declared_set:
            covered_by_declaration.append(caller)
            continue
        if edge.source_file in edited_files_set:
            covered_by_edit.append(caller)
            continue
        if caller in passing_tests_set or _short_name(caller) in passing_tests_set:
            covered_by_test.append(caller)
            continue
        uncovered.append(caller)

    getattr_advisories = _getattr_advisories_for(graph, edited_set)

    return UnderEditReport(
        modified_symbols=tuple(sorted(edited_set)),
        downstream_callers=tuple(sorted(downstream.keys())),
        covered_by_test=tuple(sorted(covered_by_test)),
        covered_by_edit=tuple(sorted(covered_by_edit)),
        covered_by_declaration=tuple(sorted(covered_by_declaration)),
        uncovered=tuple(sorted(uncovered)),
        generated_excluded=tuple(sorted(set(generated_excluded))),
        getattr_advisories=tuple(sorted(getattr_advisories)),
    )


# ---------------------------------------------------------------------------
# SQLite persistence — cache the graph across loop entries
# ---------------------------------------------------------------------------


_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbols (
        qualified_name TEXT PRIMARY KEY,
        source_file TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        kind TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS call_edges (
        caller TEXT NOT NULL,
        callee TEXT NOT NULL,
        source_file TEXT NOT NULL,
        line INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_edges (
        importer TEXT NOT NULL,
        imported_name TEXT NOT NULL,
        source_file TEXT NOT NULL,
        line INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS unsupported_files (
        path TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generated_files (
        path TEXT PRIMARY KEY
    )
    """,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn


def persist_graph(graph: SymbolGraph, db_path: Path) -> None:
    """Write ``graph`` to ``db_path``, replacing any prior contents."""
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM meta")
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM call_edges")
            conn.execute("DELETE FROM import_edges")
            conn.execute("DELETE FROM unsupported_files")
            conn.execute("DELETE FROM generated_files")
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                ("snapshot_digest", graph.snapshot_digest),
            )
            for node in graph.symbols.values():
                conn.execute(
                    "INSERT OR REPLACE INTO symbols "
                    "(qualified_name, source_file, start_line, end_line, kind) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        node.qualified_name,
                        node.source_file,
                        node.start_line,
                        node.end_line,
                        node.kind,
                    ),
                )
            for call_edge in graph.call_edges:
                conn.execute(
                    "INSERT INTO call_edges (caller, callee, source_file, line) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        call_edge.caller,
                        call_edge.callee,
                        call_edge.source_file,
                        call_edge.line,
                    ),
                )
            for import_edge in graph.import_edges:
                conn.execute(
                    "INSERT INTO import_edges "
                    "(importer, imported_name, source_file, line) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        import_edge.importer,
                        import_edge.imported_name,
                        import_edge.source_file,
                        import_edge.line,
                    ),
                )
            for path in graph.unsupported_files:
                conn.execute(
                    "INSERT OR REPLACE INTO unsupported_files (path) VALUES (?)",
                    (path,),
                )
            for path in graph.generated_files:
                conn.execute(
                    "INSERT OR REPLACE INTO generated_files (path) VALUES (?)",
                    (path,),
                )
    finally:
        conn.close()


def load_graph(db_path: Path, expected_digest: str) -> SymbolGraph | None:
    """Return the persisted graph iff its stored digest matches.

    A mismatch (or an empty database) returns ``None`` so ``build_graph``
    knows to rebuild.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("snapshot_digest",)
        ).fetchone()
        if row is None or row[0] != expected_digest:
            return None
        symbols: dict[str, SymbolNode] = {}
        for r in conn.execute(
            "SELECT qualified_name, source_file, start_line, end_line, kind FROM symbols"
        ):
            symbols[r[0]] = SymbolNode(
                qualified_name=r[0],
                source_file=r[1],
                start_line=r[2],
                end_line=r[3],
                kind=r[4],  # type: ignore[arg-type]
            )
        call_edges = tuple(
            CallEdge(caller=r[0], callee=r[1], source_file=r[2], line=r[3])
            for r in conn.execute(
                "SELECT caller, callee, source_file, line FROM call_edges"
            )
        )
        import_edges = tuple(
            ImportEdge(importer=r[0], imported_name=r[1], source_file=r[2], line=r[3])
            for r in conn.execute(
                "SELECT importer, imported_name, source_file, line FROM import_edges"
            )
        )
        unsupported = tuple(
            r[0] for r in conn.execute("SELECT path FROM unsupported_files")
        )
        generated = tuple(
            r[0] for r in conn.execute("SELECT path FROM generated_files")
        )
        return SymbolGraph(
            symbols=symbols,
            call_edges=call_edges,
            import_edges=import_edges,
            unsupported_files=unsupported,
            generated_files=generated,
            snapshot_digest=expected_digest,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# On-disk snapshot writer
# ---------------------------------------------------------------------------


def write_under_edit_snapshot(
    run_dir: Path, report: UnderEditReport
) -> Path:
    """Persist ``report`` to ``<run_dir>/under_edit.json`` and return the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "under_edit.json"
    path.write_text(
        json.dumps(report.to_canonical(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# RACT 0.4.0
