"""SQLite-backed graph index for the memory-discipline pipeline.

Ships the :class:`GraphIndex` store + :class:`EdgeRow` value type +
six read helpers (callers_of / callees_of / blast_radius /
path_between / orphans / hotspots) + insert / delete write paths.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` section
"The three indexes / Graph index". Rationale: ADR-0033.

The store lives at ``.rack/index/graph.db`` in a real repo; tests
open a temp path. Schema is loaded from
``graph_index_schema.sql`` on connection open (idempotent CREATEs
so the loader is safe against an existing store).

Every edge references a ``symbols.id`` in the module_02
:class:`~ract.memory.symbol_index.SymbolIndex`. The two stores
live in separate SQLite databases at production time, so
foreign keys are NOT declared at the schema level; the module_03
:mod:`~ract.memory.graph_populator` maintains referential
integrity through a source-file-scoped delete + re-insert path
(watcher wiring lands in module_09).

The query API accepts an optional
:class:`~ract.memory.budget.BudgetAccountant` on every read helper
so callers can seat the token cost of a graph traversal against
the same accountant as the model call it feeds (memory-discipline
axiom 1: every function invocation declares and respects a token
budget).

Chunker-parity constraint (module_02 POST-A): the graph store
does not synthesize "orphan" edges for callees the symbol index
never emitted. A caller of :meth:`GraphIndex.orphans` reads only
symbol ids the symbol index recorded; a missing Rust ``type X``
row (module_02 gap 4) does not surface as a false orphan.

FTS constraint (module_02 POST-C corollary): the graph store
never mirrors symbol text. Edge-side queries JOIN the module_02
``symbols_fts`` when they need to filter by symbol text, they
never build a parallel FTS5 layer.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Iterable, NamedTuple

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import BudgetAccountant, BudgetSection
from ract.memory.symbol_index import SymbolIndex, SymbolRow


SCHEMA_PATH: Path = Path(__file__).resolve().parent / "graph_index_schema.sql"
"""Location of the shipped schema."""

CURRENT_SCHEMA_VERSION: str = "v1"
"""Highest schema version the shipped loader knows about."""

EDGE_TYPES: frozenset[str] = frozenset(
    {"calls", "imports", "inherits", "implements", "references"}
)
"""Edge-type vocabulary per master spec §Graph index."""

NEIGHBORHOOD_SOURCES: frozenset[str] = frozenset({"lsp", "symbol_only"})
"""Provenance labels the populator writes into edges.

``lsp`` is the LSP-driven populator; ``symbol_only`` is the
fallback (:mod:`~ract.memory.lsp_fallback`) that populates a
self-referential edge when the LSP is missing so downstream
retrieval can distinguish "no neighborhood" from "the symbol
calls itself".
"""


class GraphIndexError(RuntimeError):
    """Raised on caller-side misuse of the graph index API."""


class EdgeRow(NamedTuple):
    """One row in the ``edges`` table.

    Columns match the SQL schema order (see
    ``graph_index_schema.sql``). ``id`` is ``None`` on newly-
    constructed rows and populated by
    :meth:`GraphIndex.insert_edge` after the INSERT lands.

    - ``source_symbol_id`` / ``target_symbol_id`` reference
      ``symbols.id`` in module_02's store.
    - ``edge_type`` is one of :data:`EDGE_TYPES`.
    - ``location_file`` / ``location_line`` cite the source location
      where the reference appears (a call site line, an import
      statement line, etc.); ``None`` for edges the populator
      derives without a specific location (e.g. containment).
    - ``strength`` is the per-edge weight; the LSP populator sets
      this to the reference count so the hotspots query can rank
      by weight. Defaults to 1.
    - ``neighborhood_source`` is one of :data:`NEIGHBORHOOD_SOURCES`;
      ``symbol_only`` marks the fallback path.
    """

    id: int | None
    source_symbol_id: int
    target_symbol_id: int
    edge_type: str
    location_file: str | None
    location_line: int | None
    strength: int
    neighborhood_source: str


_ROW_COLUMNS: tuple[str, ...] = (
    "id",
    "source_symbol_id",
    "target_symbol_id",
    "edge_type",
    "location_file",
    "location_line",
    "strength",
    "neighborhood_source",
)


def _row_from_sqlite(row: sqlite3.Row) -> EdgeRow:
    """Materialise an :class:`EdgeRow` from a ``sqlite3.Row``."""
    return EdgeRow(
        id=row["id"],
        source_symbol_id=row["source_symbol_id"],
        target_symbol_id=row["target_symbol_id"],
        edge_type=row["edge_type"],
        location_file=row["location_file"],
        location_line=row["location_line"],
        strength=row["strength"] if row["strength"] is not None else 1,
        neighborhood_source=(
            row["neighborhood_source"]
            if row["neighborhood_source"] is not None
            else "lsp"
        ),
    )


def _seat_budget(
    accountant: BudgetAccountant | None,
    section_name: str,
    row_count: int,
) -> None:
    """Seat the token cost of a graph traversal against ``accountant``.

    Axiom 1: every function invocation that reaches the model
    declares and respects a token budget. Graph queries feed the
    model's retrieval bundle, so the traversal cost participates
    in the same accountant. A 60-byte-per-row proxy is used for
    the token estimate; the caller can pass ``accountant=None`` to
    skip seating for pure diagnostic reads.

    ``section_name`` is disambiguated by row_count so multiple
    traversal calls on the same accountant do not collide on the
    single-write-per-section invariant.
    """
    if accountant is None:
        return
    cost = max(1, row_count) * 4  # ~4 tokens per edge (id + type + two ids)
    marker = f"{section_name}:{row_count}".encode("utf-8")
    section = BudgetSection(
        name=f"graph.{section_name}.{hashlib.sha256(marker).hexdigest()[:8]}",
        token_count=cost,
        content_hash=hashlib.sha256(marker).hexdigest(),
    )
    accountant.seat(section)


class GraphIndex:
    """SQLite-backed graph index — call/import/inherit/reference edges.

    Opens (creating if missing) a SQLite store at ``db_path``. The
    schema is applied idempotently on every open so a store carried
    forward from a prior module_03 build gets any additive changes.

    ``symbol_index`` is the module_02 store the graph edges
    reference; it is retained on the instance so read helpers can
    hydrate an id-to-symbol lookup without a fresh open. The graph
    store and the symbol store are separate SQLite databases (they
    can be attached with :meth:`attach_symbol_store` to run
    integrity checks against the symbol table); production writes
    keep them decoupled.

    Use as a context manager or manage manually with :meth:`close`.
    """

    def __init__(
        self,
        db_path: Path | str = ":memory:",
        symbol_index: SymbolIndex | None = None,
    ) -> None:
        self._db_path: str = str(db_path)
        self._symbol_index: SymbolIndex | None = symbol_index
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        if self._db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._apply_schema()

    def _apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "GraphIndex":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except sqlite3.ProgrammingError:
            pass

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection (test / debug use only)."""
        return self._conn

    @property
    def db_path(self) -> str:
        """Return the store path (or ``:memory:`` for in-memory)."""
        return self._db_path

    @property
    def symbol_index(self) -> SymbolIndex | None:
        """Return the attached symbol index (if any)."""
        return self._symbol_index

    def schema_versions(self) -> list[str]:
        """Return every schema version this store has ever been at."""
        rows = self._conn.execute("SELECT version FROM schema_version").fetchall()
        return [row["version"] for row in rows]

    def count(self) -> int:
        """Return the total number of edges in the store."""
        cur = self._conn.execute("SELECT count(*) AS n FROM edges")
        return int(cur.fetchone()["n"])

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_edge(self, edge: EdgeRow) -> int:
        """Insert ``edge`` (or bump strength if the edge already exists).

        Unique key is (source, target, edge_type, location_file,
        location_line). ON CONFLICT DO UPDATE accumulates strength
        so a re-populated file (watcher save + LSP re-query) does
        not lose the accumulated weight.
        """
        if edge.edge_type not in EDGE_TYPES:
            raise GraphIndexError(
                f"insert_edge: edge_type {edge.edge_type!r} not in {EDGE_TYPES!r}"
            )
        if edge.neighborhood_source not in NEIGHBORHOOD_SOURCES:
            raise GraphIndexError(
                f"insert_edge: neighborhood_source {edge.neighborhood_source!r} "
                f"not in {NEIGHBORHOOD_SOURCES!r}"
            )
        cur = self._conn.execute(
            """
            INSERT INTO edges (
                source_symbol_id, target_symbol_id, edge_type,
                location_file, location_line, strength, neighborhood_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_symbol_id, target_symbol_id, edge_type,
                          location_file, location_line) DO UPDATE SET
                strength = edges.strength + excluded.strength,
                neighborhood_source = excluded.neighborhood_source
            """,
            (
                edge.source_symbol_id,
                edge.target_symbol_id,
                edge.edge_type,
                edge.location_file,
                edge.location_line,
                edge.strength,
                edge.neighborhood_source,
            ),
        )
        self._conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        got = self._conn.execute(
            """
            SELECT id FROM edges
            WHERE source_symbol_id = ? AND target_symbol_id = ?
              AND edge_type = ?
              AND location_file IS ? AND location_line IS ?
            """,
            (
                edge.source_symbol_id,
                edge.target_symbol_id,
                edge.edge_type,
                edge.location_file,
                edge.location_line,
            ),
        ).fetchone()
        if got is None:
            raise GraphIndexError(
                f"insert_edge: post-conflict id lookup failed for {edge!r}"
            )
        return int(got["id"])

    def insert_edges(self, edges: Iterable[EdgeRow]) -> list[int]:
        """Insert every edge in ``edges`` under a single transaction.

        Wraps the batch in BEGIN/COMMIT so a partial failure in the
        middle of an LSP-populator batch leaves the store in the
        pre-batch state (Second Pass Q1: mid-build LSP crash does
        not commit partial edges).
        """
        assigned: list[int] = []
        try:
            self._conn.execute("BEGIN")
            for edge in edges:
                if edge.edge_type not in EDGE_TYPES:
                    raise GraphIndexError(
                        f"insert_edges: edge_type {edge.edge_type!r} not in "
                        f"{EDGE_TYPES!r}"
                    )
                if edge.neighborhood_source not in NEIGHBORHOOD_SOURCES:
                    raise GraphIndexError(
                        f"insert_edges: neighborhood_source "
                        f"{edge.neighborhood_source!r} not in "
                        f"{NEIGHBORHOOD_SOURCES!r}"
                    )
                cur = self._conn.execute(
                    """
                    INSERT INTO edges (
                        source_symbol_id, target_symbol_id, edge_type,
                        location_file, location_line, strength,
                        neighborhood_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source_symbol_id, target_symbol_id,
                                  edge_type, location_file, location_line)
                    DO UPDATE SET
                        strength = edges.strength + excluded.strength,
                        neighborhood_source = excluded.neighborhood_source
                    """,
                    (
                        edge.source_symbol_id,
                        edge.target_symbol_id,
                        edge.edge_type,
                        edge.location_file,
                        edge.location_line,
                        edge.strength,
                        edge.neighborhood_source,
                    ),
                )
                assigned.append(int(cur.lastrowid or 0))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return assigned

    def delete_by_source_file(self, path: str) -> int:
        """Delete every edge whose ``location_file`` matches ``path``.

        Returns the number of rows deleted. The graph_populator's
        per-file update path calls this before re-running the LSP
        query for the file so a symbol removed from the file does
        not leave a dangling edge behind.
        """
        cur = self._conn.execute("DELETE FROM edges WHERE location_file = ?", (path,))
        self._conn.commit()
        return cur.rowcount

    def delete_by_symbol(self, symbol_id: int) -> int:
        """Delete every edge where ``symbol_id`` is source or target.

        Called when a symbol is removed from the module_02 store
        (a class definition deleted from a source file). Both
        endpoints of the edge are checked so a dangling caller or
        callee is cleaned up in one pass.
        """
        cur = self._conn.execute(
            "DELETE FROM edges WHERE source_symbol_id = ? OR target_symbol_id = ?",
            (symbol_id, symbol_id),
        )
        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def callers_of(
        self,
        symbol_id: int,
        max_hops: int = 1,
        accountant: BudgetAccountant | None = None,
    ) -> list[EdgeRow]:
        """Return the edges whose target is ``symbol_id`` (up to ``max_hops``).

        1-hop returns direct callers; higher hops walk backwards
        through the ``calls`` and ``references`` edges to surface
        transitive callers. Self-referential fallback edges
        (``neighborhood_source == 'symbol_only'``) are excluded from
        the transitive walk so a symbol-only degradation does not
        inflate the caller count.
        """
        if max_hops < 1:
            raise GraphIndexError("callers_of: max_hops must be >= 1")
        seen_edge_ids: set[int] = set()
        results: list[EdgeRow] = []
        frontier = {symbol_id}
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            cur = self._conn.execute(
                f"""
                SELECT * FROM edges
                WHERE target_symbol_id IN ({placeholders})
                  AND neighborhood_source = 'lsp'
                ORDER BY id
                """,
                tuple(frontier),
            )
            rows = [_row_from_sqlite(row) for row in cur.fetchall()]
            next_frontier: set[int] = set()
            for row in rows:
                if row.id in seen_edge_ids:
                    continue
                seen_edge_ids.add(row.id)  # type: ignore[arg-type]
                results.append(row)
                next_frontier.add(row.source_symbol_id)
            frontier = next_frontier
        _seat_budget(accountant, "callers_of", len(results))
        return results

    def callees_of(
        self,
        symbol_id: int,
        max_hops: int = 1,
        accountant: BudgetAccountant | None = None,
    ) -> list[EdgeRow]:
        """Return the edges whose source is ``symbol_id`` (up to ``max_hops``)."""
        if max_hops < 1:
            raise GraphIndexError("callees_of: max_hops must be >= 1")
        seen_edge_ids: set[int] = set()
        results: list[EdgeRow] = []
        frontier = {symbol_id}
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            cur = self._conn.execute(
                f"""
                SELECT * FROM edges
                WHERE source_symbol_id IN ({placeholders})
                  AND neighborhood_source = 'lsp'
                ORDER BY id
                """,
                tuple(frontier),
            )
            rows = [_row_from_sqlite(row) for row in cur.fetchall()]
            next_frontier: set[int] = set()
            for row in rows:
                if row.id in seen_edge_ids:
                    continue
                seen_edge_ids.add(row.id)  # type: ignore[arg-type]
                results.append(row)
                next_frontier.add(row.target_symbol_id)
            frontier = next_frontier
        _seat_budget(accountant, "callees_of", len(results))
        return results

    def blast_radius(
        self,
        symbol_id: int,
        max_hops: int = 2,
        accountant: BudgetAccountant | None = None,
    ) -> list[SymbolRow]:
        """Return every symbol reachable from ``symbol_id`` within ``max_hops``.

        Symmetric walk: follows both incoming and outgoing edges up
        to ``max_hops`` and returns the union as :class:`SymbolRow`
        values (requires an attached symbol index). ``symbol_id``
        itself is included in the result if the walk touched it via
        an edge.
        """
        if max_hops < 1:
            raise GraphIndexError("blast_radius: max_hops must be >= 1")
        if self._symbol_index is None:
            raise GraphIndexError(
                "blast_radius: requires a symbol index; construct GraphIndex "
                "with symbol_index= or attach one before calling."
            )
        seen_ids: set[int] = set()
        visited: set[int] = {symbol_id}
        frontier: set[int] = {symbol_id}
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            cur = self._conn.execute(
                f"""
                SELECT source_symbol_id AS a, target_symbol_id AS b
                FROM edges
                WHERE (source_symbol_id IN ({placeholders})
                       OR target_symbol_id IN ({placeholders}))
                  AND neighborhood_source = 'lsp'
                """,
                tuple(frontier) + tuple(frontier),
            )
            next_frontier: set[int] = set()
            for row in cur.fetchall():
                for endpoint in (row["a"], row["b"]):
                    if endpoint == symbol_id or endpoint in visited:
                        continue
                    seen_ids.add(endpoint)
                    visited.add(endpoint)
                    next_frontier.add(endpoint)
            frontier = next_frontier
        symbols: list[SymbolRow] = []
        for sid in sorted(seen_ids):
            row = self._symbol_index.connection.execute(
                "SELECT * FROM symbols WHERE id = ?", (sid,)
            ).fetchone()
            if row is not None:
                from ract.memory.symbol_index import _row_from_sqlite as sym_row

                symbols.append(sym_row(row))
        _seat_budget(accountant, "blast_radius", len(symbols))
        return symbols

    def path_between(
        self,
        source_id: int,
        target_id: int,
        max_hops: int = 6,
        accountant: BudgetAccountant | None = None,
    ) -> list[EdgeRow] | None:
        """Return the shortest edge path from ``source_id`` to ``target_id``.

        BFS over the ``calls`` / ``references`` / ``imports`` edges
        with a maximum depth of ``max_hops``. Returns ``None`` if no
        path exists within the depth budget. The returned list is
        ordered from source to target.
        """
        if max_hops < 1:
            raise GraphIndexError("path_between: max_hops must be >= 1")
        if source_id == target_id:
            return []
        # BFS with parent pointers, edge-based reconstruction.
        parents: dict[int, tuple[int, EdgeRow]] = {}
        frontier: list[int] = [source_id]
        seen: set[int] = {source_id}
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            cur = self._conn.execute(
                f"""
                SELECT * FROM edges
                WHERE source_symbol_id IN ({placeholders})
                  AND neighborhood_source = 'lsp'
                ORDER BY id
                """,
                tuple(frontier),
            )
            next_frontier: list[int] = []
            for row in cur.fetchall():
                edge = _row_from_sqlite(row)
                if edge.target_symbol_id in seen:
                    continue
                seen.add(edge.target_symbol_id)
                parents[edge.target_symbol_id] = (edge.source_symbol_id, edge)
                if edge.target_symbol_id == target_id:
                    # Reconstruct the path.
                    path: list[EdgeRow] = []
                    cur_id = target_id
                    while cur_id in parents:
                        parent_id, parent_edge = parents[cur_id]
                        path.append(parent_edge)
                        cur_id = parent_id
                    path.reverse()
                    _seat_budget(accountant, "path_between", len(path))
                    return path
                next_frontier.append(edge.target_symbol_id)
            frontier = next_frontier
        _seat_budget(accountant, "path_between", 0)
        return None

    def orphans(
        self,
        exclude_public: bool = True,
        accountant: BudgetAccountant | None = None,
    ) -> list[SymbolRow]:
        """Return symbols with zero incoming ``calls`` / ``references`` edges.

        Dead-code candidates. Requires an attached symbol index (the
        query walks every symbol id known to module_02 and filters
        against the edge table).

        ``exclude_public=True`` (default; Lateral Chain branch E)
        filters out symbols whose ``visibility`` is ``'public'`` so
        the caller of the dead-code playbook does not see the public
        API as a candidate.

        Chunker-parity constraint (module_02 POST-A): the orphan
        query reads from the symbol store; symbols the symbol index
        never emitted (e.g. Rust ``type X`` today, module_02 gap 4)
        never surface as false orphans because they are not in the
        input set at all.
        """
        if self._symbol_index is None:
            raise GraphIndexError(
                "orphans: requires a symbol index; construct GraphIndex "
                "with symbol_index= or attach one before calling."
            )
        # Build the set of symbol ids that have any inbound lsp edge.
        cur = self._conn.execute(
            "SELECT DISTINCT target_symbol_id FROM edges "
            "WHERE neighborhood_source = 'lsp'"
        )
        referenced_ids: set[int] = {row["target_symbol_id"] for row in cur.fetchall()}
        # Fetch every symbol id from module_02.
        sym_cur = self._symbol_index.connection.execute(
            "SELECT * FROM symbols ORDER BY file_path, start_line"
        )
        from ract.memory.symbol_index import _row_from_sqlite as sym_row

        orphaned: list[SymbolRow] = []
        for sql_row in sym_cur.fetchall():
            symbol = sym_row(sql_row)
            if symbol.id in referenced_ids:
                continue
            if exclude_public and symbol.visibility == "public":
                continue
            orphaned.append(symbol)
        _seat_budget(accountant, "orphans", len(orphaned))
        return orphaned

    def hotspots(
        self,
        threshold: int,
        accountant: BudgetAccountant | None = None,
    ) -> list[EdgeRow]:
        """Return edges whose ``strength`` is at or above ``threshold``.

        High-strength edges are the "hot" call sites the retrieve
        primitive prioritises when a query falls under budget
        pressure.
        """
        if threshold < 1:
            raise GraphIndexError("hotspots: threshold must be >= 1")
        cur = self._conn.execute(
            """
            SELECT * FROM edges
            WHERE strength >= ? AND neighborhood_source = 'lsp'
            ORDER BY strength DESC, id ASC
            """,
            (threshold,),
        )
        rows = [_row_from_sqlite(row) for row in cur.fetchall()]
        _seat_budget(accountant, "hotspots", len(rows))
        return rows

    def edges_for_file(self, path: str) -> list[EdgeRow]:
        """Return every edge whose ``location_file`` matches ``path``.

        Used by the graph_populator's per-file update path to
        confirm the file's edges are gone after a
        :meth:`delete_by_source_file` call.
        """
        cur = self._conn.execute(
            "SELECT * FROM edges WHERE location_file = ? ORDER BY id", (path,)
        )
        return [_row_from_sqlite(row) for row in cur.fetchall()]


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "EDGE_TYPES",
    "EdgeRow",
    "GraphIndex",
    "GraphIndexError",
    "NEIGHBORHOOD_SOURCES",
    "SCHEMA_PATH",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
