"""SQLite-backed symbol index for the memory-discipline pipeline.

Ships the :class:`SymbolIndex` store + :class:`SymbolRow` value type +
five query helpers (find_by_name / find_by_pattern / find_in_file /
find_by_text / find_by_hash) + insert / delete / replace-file paths.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` section
"The three indexes / Symbol index". Rationale: ADR-0032.

The store lives at ``.rack/index/symbols.db`` in a real repo; tests
open a temp path. Schema is loaded from
``symbol_index_schema.sql`` on connection open (idempotent CREATEs
so the loader is safe against an existing store).

Language-agnostic on purpose. ``SymbolRow.language`` is a filter, not
a partition (Lateral Chain branch E): ``find_by_name("User")``
returns a Python ``User`` class and a TypeScript ``User`` type in one
result set.

Import-time dependency on module_01 ``BudgetAccountant`` is
deliberately absent. Indexing is a deterministic non-model surface
and does not seat context sections; the ``token_count`` field the
schema carries is what the module_04 semantic index and module_05
retrieve primitive read against a caller-supplied accountant.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from types import TracebackType
from typing import Any, NamedTuple

from ract.core.module_identity import _module_knot, register_module_knot


SCHEMA_PATH: Path = Path(__file__).resolve().parent / "symbol_index_schema.sql"
"""Location of the shipped schema."""

CURRENT_SCHEMA_VERSION: str = "v1"
"""Highest schema version the shipped loader knows about."""


class SqliteMissingFTS5Error(RuntimeError):
    """Raised when the loaded SQLite build lacks the FTS5 module.

    macOS system Python has historically shipped without FTS5
    compiled in. The store's FTS-backed :meth:`SymbolIndex.find_by_text`
    would trip on the first virtual-table CREATE; this error is raised
    ahead of that with a specific fix (install ``pysqlite3-binary`` or
    a Python with FTS5).
    """


class SymbolIndexError(RuntimeError):
    """Raised on caller-side misuse of the symbol index API."""


class SymbolRow(NamedTuple):
    """One row in the ``symbols`` table.

    Columns match the SQL schema order (see
    ``symbol_index_schema.sql``). ``id`` is ``None`` on newly-parsed
    rows and populated by :meth:`SymbolIndex.replace_file` after the
    INSERT lands.

    ``kind`` is a language-agnostic label: ``function``, ``class``,
    ``method``, ``constant``, ``type``, ``interface``, ``struct``,
    ``enum``, ``trait``, ``impl``, ``module``. Individual language
    parsers under :mod:`ract.memory.languages` produce a subset.

    ``visibility`` is a language-agnostic label: ``public``,
    ``private``, ``protected``, or ``None`` when the language has no
    such marker at the symbol site. Python treats leading-underscore
    names as ``private``.
    """

    id: int | None
    name: str
    kind: str
    file_path: str
    start_line: int | None
    end_line: int | None
    signature: str | None
    docstring: str | None
    visibility: str | None
    parent_symbol_id: int | None
    language: str | None
    content_hash: str | None
    token_count: int | None
    updated_at: int | None


_ROW_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "kind",
    "file_path",
    "start_line",
    "end_line",
    "signature",
    "docstring",
    "visibility",
    "parent_symbol_id",
    "language",
    "content_hash",
    "token_count",
    "updated_at",
)


def _row_from_sqlite(row: sqlite3.Row) -> SymbolRow:
    """Materialise a :class:`SymbolRow` from a ``sqlite3.Row``."""
    return SymbolRow(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        file_path=row["file_path"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        signature=row["signature"],
        docstring=row["docstring"],
        visibility=row["visibility"],
        parent_symbol_id=row["parent_symbol_id"],
        language=row["language"],
        content_hash=row["content_hash"],
        token_count=row["token_count"],
        updated_at=row["updated_at"],
    )


def _regexp(pattern: str, value: str | None) -> bool:
    """SQLite REGEXP callback — full ``re.search`` semantics.

    Registered on every connection so ``find_by_pattern`` can push
    the filter to SQL. ``None`` values do not match.
    """
    if value is None:
        return False
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def _assert_fts5(conn: sqlite3.Connection) -> None:
    """Raise :class:`SqliteMissingFTS5Error` if the build lacks FTS5."""
    rows = conn.execute("PRAGMA compile_options").fetchall()
    if not any("ENABLE_FTS5" in str(row[0]) for row in rows):
        raise SqliteMissingFTS5Error(
            "The loaded SQLite build lacks the FTS5 module. Symbol index "
            "requires FTS5 for docstring / name full-text search. Install a "
            "SQLite build with FTS5 (``pysqlite3-binary`` on PyPI ships one) "
            "or rebuild Python's ``_sqlite3`` with ``--enable-fts5``."
        )


class SymbolIndex:
    """SQLite-backed symbol index — the first-order lookup for v0.5.0.

    Opens (creating if missing) a SQLite store at ``db_path``. The
    schema is applied idempotently on every open so a store carried
    forward from a prior module_02 build gets any additive changes.

    Use as a context manager (``with SymbolIndex(path) as idx: ...``)
    or manage manually with :meth:`close`. Concurrent readers are
    supported by SQLite's default WAL mode which this class opts into
    on open.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path: str = str(db_path)
        # ``check_same_thread=False`` so the watcher's daemon threads
        # can drive writes through the same connection. Concurrent
        # access is serialised at the watcher's threading.Lock
        # (``SymbolIndexWatcher._index_lock``); pure-read callers
        # tolerate SQLite's internal locking without a Python lock.
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        _assert_fts5(self._conn)
        self._conn.create_function("REGEXP", 2, _regexp, deterministic=True)
        if self._db_path != ":memory:":
            # WAL is a durable-store concern; :memory: rejects it.
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._apply_schema()

    def _apply_schema(self) -> None:
        """Load and execute the shipped schema.

        Idempotent — every CREATE is ``IF NOT EXISTS``. The
        ``schema_version`` table gains its ``v1`` row on first apply.
        """
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "SymbolIndex":
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

    def schema_versions(self) -> list[str]:
        """Return every schema version this store has ever been at."""
        rows = self._conn.execute("SELECT version FROM schema_version").fetchall()
        return [row["version"] for row in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_or_update(self, row: SymbolRow) -> int:
        """Insert ``row`` (or update the existing row on the unique key).

        Unique key is ``(file_path, kind, name, start_line)``; the
        parser produces stable values for those four fields even
        across whitespace-only edits, so an unchanged symbol keeps its
        ``id`` across re-indexing. Returns the row's ``id``.
        """
        stamp = row.updated_at if row.updated_at is not None else int(time.time())
        cur = self._conn.execute(
            """
            INSERT INTO symbols (
                name, kind, file_path, start_line, end_line, signature,
                docstring, visibility, parent_symbol_id, language,
                content_hash, token_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (file_path, kind, name, start_line) DO UPDATE SET
                end_line = excluded.end_line,
                signature = excluded.signature,
                docstring = excluded.docstring,
                visibility = excluded.visibility,
                parent_symbol_id = excluded.parent_symbol_id,
                language = excluded.language,
                content_hash = excluded.content_hash,
                token_count = excluded.token_count,
                updated_at = excluded.updated_at
            """,
            (
                row.name,
                row.kind,
                row.file_path,
                row.start_line,
                row.end_line,
                row.signature,
                row.docstring,
                row.visibility,
                row.parent_symbol_id,
                row.language,
                row.content_hash,
                row.token_count,
                stamp,
            ),
        )
        self._conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        # ON CONFLICT DO UPDATE keeps the original id; look it up.
        got = self._conn.execute(
            "SELECT id FROM symbols WHERE file_path = ? AND kind = ? "
            "AND name = ? AND start_line IS ?",
            (row.file_path, row.kind, row.name, row.start_line),
        ).fetchone()
        if got is None:
            raise SymbolIndexError(
                f"insert_or_update: post-conflict id lookup failed for {row!r}"
            )
        return int(got["id"])

    def delete_by_file(self, file_path: str) -> int:
        """Delete every row for ``file_path``. Returns the number deleted."""
        cur = self._conn.execute(
            "DELETE FROM symbols WHERE file_path = ?", (file_path,)
        )
        self._conn.commit()
        return cur.rowcount

    def replace_file(self, file_path: str, rows: list[SymbolRow]) -> list[int]:
        """Replace every row for ``file_path`` with ``rows``.

        Wraps the delete + insert in a single transaction so a query
        issued mid-operation never sees a partial file. Returns the
        list of ids assigned (in the same order as ``rows``).

        A ``parent_symbol_id`` value in the input ``rows`` is
        preserved on insert; the parser today emits ``None`` because
        parent linkage lands with the module_03 graph index (Flagged
        gap for module_02 close).
        """
        assigned: list[int] = []
        try:
            self._conn.execute("BEGIN")
            self._conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
            for row in rows:
                stamp = (
                    row.updated_at if row.updated_at is not None else int(time.time())
                )
                cur = self._conn.execute(
                    """
                    INSERT INTO symbols (
                        name, kind, file_path, start_line, end_line, signature,
                        docstring, visibility, parent_symbol_id, language,
                        content_hash, token_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.name,
                        row.kind,
                        row.file_path,
                        row.start_line,
                        row.end_line,
                        row.signature,
                        row.docstring,
                        row.visibility,
                        row.parent_symbol_id,
                        row.language,
                        row.content_hash,
                        row.token_count,
                        stamp,
                    ),
                )
                assigned.append(int(cur.lastrowid or 0))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return assigned

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def find_by_name(
        self, name: str, kind_filter: str | None = None
    ) -> list[SymbolRow]:
        """Return every symbol with exact ``name`` (optionally filtered by kind)."""
        if kind_filter is None:
            cur = self._conn.execute(
                "SELECT * FROM symbols WHERE name = ? ORDER BY file_path, start_line",
                (name,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM symbols WHERE name = ? AND kind = ? "
                "ORDER BY file_path, start_line",
                (name, kind_filter),
            )
        return [_row_from_sqlite(row) for row in cur.fetchall()]

    def find_by_pattern(
        self, regex: str, kind_filter: str | None = None
    ) -> list[SymbolRow]:
        """Return every symbol whose name matches ``regex`` (``re.search``)."""
        # Validate the pattern here so the caller gets a Python re.error
        # rather than an opaque SQLite silent-no-match.
        re.compile(regex)
        if kind_filter is None:
            cur = self._conn.execute(
                "SELECT * FROM symbols WHERE name REGEXP ? "
                "ORDER BY file_path, start_line",
                (regex,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM symbols WHERE name REGEXP ? AND kind = ? "
                "ORDER BY file_path, start_line",
                (regex, kind_filter),
            )
        return [_row_from_sqlite(row) for row in cur.fetchall()]

    def find_in_file(self, path: str) -> list[SymbolRow]:
        """Return every symbol declared in ``path`` (in source order)."""
        cur = self._conn.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY start_line",
            (path,),
        )
        return [_row_from_sqlite(row) for row in cur.fetchall()]

    def find_by_text(self, query: str) -> list[SymbolRow]:
        """Return every symbol whose name or docstring matches ``query`` (FTS5)."""
        cur = self._conn.execute(
            "SELECT symbols.* FROM symbols "
            "JOIN symbols_fts ON symbols.id = symbols_fts.rowid "
            "WHERE symbols_fts MATCH ? ORDER BY symbols.file_path, symbols.start_line",
            (query,),
        )
        return [_row_from_sqlite(row) for row in cur.fetchall()]

    def find_by_hash(self, content_hash: str) -> list[SymbolRow]:
        """Return every symbol whose ``content_hash`` matches (dedup lookup)."""
        cur = self._conn.execute(
            "SELECT * FROM symbols WHERE content_hash = ? "
            "ORDER BY file_path, start_line",
            (content_hash,),
        )
        return [_row_from_sqlite(row) for row in cur.fetchall()]

    def count(self) -> int:
        """Return the total number of rows in the store."""
        cur = self._conn.execute("SELECT count(*) AS n FROM symbols")
        return int(cur.fetchone()["n"])

    def files(self) -> list[str]:
        """Return the sorted list of file paths that have any indexed symbols."""
        cur = self._conn.execute(
            "SELECT DISTINCT file_path FROM symbols ORDER BY file_path"
        )
        return [row["file_path"] for row in cur.fetchall()]

    def file_mtimes(self) -> dict[str, int]:
        """Return the ``file_path -> max(updated_at)`` map.

        Watcher's periodic-scan fallback (Lateral Chain branch B) uses
        this to spot files whose filesystem mtime is newer than the
        stored ``updated_at`` and re-index them.
        """
        cur = self._conn.execute(
            "SELECT file_path, MAX(updated_at) AS mtime FROM symbols GROUP BY file_path"
        )
        return {row["file_path"]: int(row["mtime"] or 0) for row in cur.fetchall()}


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "SCHEMA_PATH",
    "SqliteMissingFTS5Error",
    "SymbolIndex",
    "SymbolIndexError",
    "SymbolRow",
]


def as_dict(row: SymbolRow) -> dict[str, Any]:
    """Return ``row`` as a plain dict keyed by column name.

    Convenience for tests and downstream modules (module_04 semantic
    index reads the row to feed the embedding chunker).
    """
    return dict(zip(_ROW_COLUMNS, row, strict=True))


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
