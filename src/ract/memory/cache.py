"""SQLite-backed query cache for the retrieve primitive.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Cache
layer. Keys on ``(query_hash, repo_commit_hash)``: a query that fires
against the same repo state (same tree at the same commit) returns
the cached bundle without touching the three indexes. On a file save
the module_02 watcher publishes an invalidation via
:meth:`RetrievalCache.invalidate_by_symbol` so bundles that reference
that symbol drop out of the cache.

v0.5.1 wiring module_08 (Lens E MEM-E-01) closure: TTL enforcement.
Every entry records a ``created_at`` timestamp; :meth:`lookup` now
consults ``ttl_seconds`` (default 3600s = 1h; configurable per
instance) and drops the row on miss when it has aged past the TTL.
The v0.5.0 shape recorded ``created_at`` but never read it -- a
long-lived process could serve indefinitely-old bundles between
watcher invalidations. Wired paired with
:class:`~ract.memory.watcher.SymbolIndexWatcher` cascading to
:meth:`invalidate_by_file` on every source change so an in-place
edit and an idle bundle both drop stale entries in production.

The cache lives at ``.rack/cache/retrieval.db`` in a real repo; tests
open a temp path. Schema is created idempotently at open time so a
loader is safe against an existing store.

The cache never materialises a live :class:`Chunk` reference. It
stores a JSON projection of the bundle (bodies + metadata) and
re-hydrates on lookup. This decouples cache stability from a running
retrieve call and lets the cache survive Python restarts.

Cache-key digest reads the canonical-JSON projection of the query
plus the repo commit hash. Two queries that differ only in Python
dict ordering produce the same key; two queries that differ in a
single field (a new keyword, a graph seed added) produce different
keys.

Concurrency: WAL mode is enabled at open time so parallel retrieve
calls can read concurrently and the watcher's invalidation write does
not stall a reader. A per-instance :class:`threading.Lock` serialises
writes on the same connection object.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

from ract.canonical import dumps_jcs
from ract.core.module_identity import _module_knot, register_module_knot


CURRENT_SCHEMA_VERSION: str = "v1"

DEFAULT_TTL_SECONDS: int = 3600
"""Default TTL for cached bundles (1 hour).

v0.5.1 wiring module_08 (Lens E MEM-E-01) closure. Overridable per
:class:`RetrievalCache` instance via the ``ttl_seconds`` constructor
argument. Set to ``0`` (or a negative value) to disable TTL
enforcement -- a caller that wants "cache forever, invalidate only
on source change" opts in explicitly.
"""


class RetrievalCacheError(RuntimeError):
    """Raised on caller-side misuse of the retrieval cache API."""


def _canonical_query_json(query_payload: dict[str, Any]) -> str:
    """Return a canonical JSON string for the query payload.

    v0.5.1 module_03: canonical bytes are RFC 8785 JCS decoded to str
    for downstream SQLite string-column storage. Sorted keys, no
    whitespace, NFC-normalised.
    """
    return dumps_jcs(query_payload).decode("utf-8")


def _cache_key(query_payload: dict[str, Any], repo_commit_hash: str) -> str:
    """Return the SHA-256 hex digest for
    ``(canonical_json(query) + repo_commit_hash)``.
    """
    hasher = hashlib.sha256()
    hasher.update(_canonical_query_json(query_payload).encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(repo_commit_hash.encode("utf-8"))
    return hasher.hexdigest()


class RetrievalCache:
    """SQLite-backed query cache.

    Use as a context manager
    (``with RetrievalCache(path) as cache: ...``) or manage manually
    via :meth:`close`.
    """

    def __init__(
        self,
        store_path: Path | str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._store_path: Path = Path(store_path).resolve()
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._store_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._lock = threading.Lock()
        # v0.5.1 wiring module_08 (Lens E MEM-E-01) closure: TTL is a
        # per-instance setting so tests can pin a short TTL
        # deterministically while production runs at DEFAULT_TTL_SECONDS.
        # A zero-or-negative value disables the TTL check (unbounded
        # cache, invalidate-on-source-change only).
        self._ttl_seconds: int = int(ttl_seconds)
        self._create_schema()

    @property
    def ttl_seconds(self) -> int:
        """Return the configured TTL in seconds."""
        return self._ttl_seconds

    def __enter__(self) -> "RetrievalCache":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release the SQLite connection."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    @property
    def store_path(self) -> Path:
        return self._store_path

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS retrieval_cache (
                cache_key TEXT PRIMARY KEY,
                query_json TEXT NOT NULL,
                repo_commit_hash TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                symbol_ids_csv TEXT NOT NULL,
                file_paths_csv TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_retrieval_cache_commit
                ON retrieval_cache (repo_commit_hash);
            """
        )

    def count(self) -> int:
        """Return the current number of cached bundles."""
        cur = self._conn.execute("SELECT count(*) AS n FROM retrieval_cache")
        return int(cur.fetchone()["n"])

    def lookup(
        self, query_payload: dict[str, Any], repo_commit_hash: str
    ) -> dict[str, Any] | None:
        """Return the cached bundle payload for ``(query, repo_commit_hash)``.

        Returns ``None`` on a miss. The returned value is the JSON-
        projected bundle payload the caller passed to :meth:`store`;
        the caller re-hydrates :class:`Chunk` instances (this module
        stays free of a chunk import so the cache can land without a
        cycle).

        v0.5.1 wiring module_08 (Lens E MEM-E-01) closure: TTL
        enforcement. An entry whose ``created_at + ttl_seconds`` is in
        the past is treated as a miss AND deleted so the cache does
        not accumulate expired rows over a long-lived process. TTL
        <= 0 disables the check (v0.5.0-compat: cache-forever mode).
        """
        key = _cache_key(query_payload, repo_commit_hash)
        cur = self._conn.execute(
            "SELECT bundle_json, created_at FROM retrieval_cache "
            "WHERE cache_key = ?",
            (key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        if self._ttl_seconds > 0:
            now = int(time.time())
            created_at = int(row["created_at"])
            if created_at + self._ttl_seconds < now:
                # Expired: delete the stale row and treat as a miss.
                with self._lock:
                    self._conn.execute(
                        "DELETE FROM retrieval_cache WHERE cache_key = ?",
                        (key,),
                    )
                return None
        return json.loads(row["bundle_json"])

    def invalidate_expired(self) -> int:
        """Drop every entry whose TTL has passed. Returns rows deleted.

        v0.5.1 wiring module_08 (Lens E MEM-E-01) closure. TTL <= 0
        disables the check and returns 0 (nothing to do). The watcher's
        periodic-scan thread invokes this on each tick so a cache
        that never sees a matching ``lookup`` still ages.
        """
        if self._ttl_seconds <= 0:
            return 0
        cutoff = int(time.time()) - self._ttl_seconds
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM retrieval_cache WHERE created_at < ?", (cutoff,)
            )
        return cur.rowcount

    def store(
        self,
        query_payload: dict[str, Any],
        repo_commit_hash: str,
        bundle_payload: dict[str, Any],
        symbol_ids: list[int],
        file_paths: list[str],
    ) -> None:
        """Store ``bundle_payload`` under the derived cache key.

        Records ``symbol_ids`` and ``file_paths`` alongside the entry
        so :meth:`invalidate_by_symbol` and :meth:`invalidate_by_file`
        can find every entry that references a changed symbol / file.
        Duplicate keys are replaced (INSERT OR REPLACE).
        """
        key = _cache_key(query_payload, repo_commit_hash)
        symbol_csv = ",".join(str(int(sid)) for sid in sorted(set(symbol_ids)))
        file_csv = "\x1f".join(sorted(set(file_paths)))
        query_json = _canonical_query_json(query_payload)
        # v0.5.1 module_03: RFC 8785 JCS canonical bytes.
        bundle_json = dumps_jcs(bundle_payload).decode("utf-8")
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO retrieval_cache (
                    cache_key, query_json, repo_commit_hash, bundle_json,
                    symbol_ids_csv, file_paths_csv, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    query_json,
                    repo_commit_hash,
                    bundle_json,
                    symbol_csv,
                    file_csv,
                    int(time.time()),
                ),
            )

    def invalidate_by_symbol(self, symbol_id: int) -> int:
        """Drop every cache entry whose bundle references ``symbol_id``.

        Returns the number of rows deleted. Called by the module_02
        watcher on file save: for each symbol whose ``content_hash``
        changed, the watcher invokes this helper and the cascade re-
        runs on the next matching query.

        Match test: the CSV row list is scanned for the exact int
        token bounded by commas or ends. This avoids
        false positives on the substring ``1`` matching inside ``12``.
        """
        needle = str(int(symbol_id))
        with self._lock:
            cur = self._conn.execute(
                """
                DELETE FROM retrieval_cache
                WHERE symbol_ids_csv = ?
                   OR symbol_ids_csv LIKE ? || ',%'
                   OR symbol_ids_csv LIKE '%,' || ? || ',%'
                   OR symbol_ids_csv LIKE '%,' || ?
                """,
                (needle, needle, needle, needle),
            )
        return cur.rowcount

    def invalidate_by_file(self, file_path: str) -> int:
        """Drop every cache entry whose bundle references ``file_path``."""
        needle = str(file_path)
        with self._lock:
            cur = self._conn.execute(
                """
                DELETE FROM retrieval_cache
                WHERE file_paths_csv = ?
                   OR file_paths_csv LIKE ? || X'1F' || '%'
                   OR file_paths_csv LIKE '%' || X'1F' || ? || X'1F' || '%'
                   OR file_paths_csv LIKE '%' || X'1F' || ?
                """,
                (needle, needle, needle, needle),
            )
        return cur.rowcount

    def invalidate_all(self) -> int:
        """Drop every entry. Returns the count deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM retrieval_cache")
        return cur.rowcount


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_TTL_SECONDS",
    "RetrievalCache",
    "RetrievalCacheError",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
