"""Incremental file watcher for the memory-discipline indexes.

Two independent invalidation paths run side by side:

- A ``watchdog`` :class:`Observer` on the repo root fires events on
  create / modify / delete. Each event is debounced (default 100 ms
  per path) and then triggers ``parse_file(path)`` + ``replace_file``
  against the :class:`SymbolIndex`.

- A periodic-scan thread compares filesystem ``mtime`` against the
  ``symbols.updated_at`` recorded per file. Any file whose ``mtime``
  is newer gets re-indexed. This closes the missed-save worry on
  Windows (Lateral Chain branch B): ``watchdog``'s Windows backend
  occasionally drops events under high write pressure, so the
  eventual-consistency guarantee lives on an independent thread. The
  Second Pass Q3 anticipator: the periodic scan runs on its OWN
  daemon thread, not the watchdog thread, so a slow parse cannot
  block the fallback.

Debouncing: file editors emit a save flood (e.g., a temp write then
an atomic rename). Without debounce, one save re-parses the file
twice. The debouncer batches events for the same path within the
window and re-parses once.

v0.5.1 wiring module_08 (Lens E MEM-E-01 + MEM-E-02) closure: the
watcher now optionally holds handles to :class:`RetrievalCache`,
:class:`~ract.memory.graph_populator.GraphPopulator`, and
:class:`~ract.memory.semantic_index.SemanticIndex` (with a semantic-
build helper). On every ``_reindex_write`` / ``_reindex_delete`` the
watcher cascades the update to each attached index so the three
memory-discipline indexes no longer drift silently. Cache
invalidation (:meth:`RetrievalCache.invalidate_by_file`) is invoked
after each cascade so a stale bundle keyed on the modified file is
dropped in the same flush. A ``memory.freshness_gap`` event fires
per cascade tick so operators can see which indexes updated and
which were absent.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.parser import SUPPORTED_EXTENSIONS, parse_file
from ract.memory.symbol_index import SymbolIndex


LOG = logging.getLogger(__name__)


@dataclass
class WatcherStats:
    """Counters exposed for tests + operational visibility."""

    events_seen: int = 0
    reindex_calls: int = 0
    delete_calls: int = 0
    periodic_scans: int = 0
    parse_errors: int = 0
    # v0.5.1 wiring module_08 counters -- one per cascade site.
    cache_invalidations: int = 0
    graph_updates: int = 0
    semantic_updates: int = 0
    graph_errors: int = 0
    semantic_errors: int = 0
    ttl_evictions: int = 0


class SymbolIndexWatcher:
    """Watchdog + periodic-scan watcher over a repo root.

    Construction does NOT start the watcher; call :meth:`start` to
    launch the observer + periodic scan threads. :meth:`stop` joins
    both. Safe to start / stop more than once.

    The watcher writes into the supplied :class:`SymbolIndex` under
    a threading lock so concurrent event + periodic-scan writes never
    collide.
    """

    def __init__(
        self,
        root: Path,
        index: SymbolIndex,
        *,
        extensions: Sequence[str] = SUPPORTED_EXTENSIONS,
        debounce_seconds: float = 0.1,
        periodic_scan_seconds: float = 30.0,
        cache: Any | None = None,
        graph_populator: Any | None = None,
        semantic_index: Any | None = None,
    ) -> None:
        """Construct the watcher.

        Backward-compat: existing callers who pass only ``root`` +
        ``index`` continue to work with the previous single-index
        behavior. The new keyword-only arguments -- ``cache``,
        ``graph_populator``, ``semantic_index`` -- are v0.5.1 wiring
        module_08 (Lens E MEM-E-01 + MEM-E-02) closures. Any subset
        may be supplied; each is optional and cascades independently.

        - ``cache``: a :class:`~ract.memory.cache.RetrievalCache`
          handle. On any reindex, the watcher calls
          :meth:`RetrievalCache.invalidate_by_file` for the changed
          path. On periodic scan ticks it also calls
          :meth:`RetrievalCache.invalidate_expired` so TTL enforcement
          runs even when no source change has fired.
        - ``graph_populator``: a
          :class:`~ract.memory.graph_populator.GraphPopulator`. On any
          reindex, the watcher calls
          :meth:`GraphPopulator.update_file`. On delete it calls
          :meth:`GraphIndex.delete_by_source_file` via the populator's
          own graph handle when accessible.
        - ``semantic_index``: a
          :class:`~ract.memory.semantic_index.SemanticIndex`. On any
          reindex, the watcher walks the file's fresh symbols and
          calls :func:`~ract.memory.semantic_builder.update_symbol`
          per symbol. On delete it calls
          :meth:`SemanticIndex.delete_by_file`.
        """
        self.root: Path = root.resolve()
        self.index: SymbolIndex = index
        self.extensions: frozenset[str] = frozenset(extensions)
        self.debounce_seconds: float = debounce_seconds
        self.periodic_scan_seconds: float = periodic_scan_seconds
        self.stats: WatcherStats = WatcherStats()

        # v0.5.1 wiring module_08 handles. Each is optional; None
        # preserves prior single-index behavior.
        self.cache: Any | None = cache
        self.graph_populator: Any | None = graph_populator
        self.semantic_index: Any | None = semantic_index

        self._observer: Any = None
        self._periodic_thread: threading.Thread | None = None
        self._stop_event: threading.Event = threading.Event()
        self._index_lock: threading.Lock = threading.Lock()
        self._pending_lock: threading.Lock = threading.Lock()
        self._pending: dict[Path, float] = {}
        self._pending_deleted: dict[Path, bool] = {}
        self._debounce_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the observer + debounce + periodic-scan threads."""
        if self._observer is not None:
            return
        self._stop_event.clear()
        handler = _EventHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.root), recursive=True)
        self._observer.start()
        self._debounce_thread = threading.Thread(
            target=self._debounce_loop, name="ract-symbol-index-debounce", daemon=True
        )
        self._debounce_thread.start()
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop, name="ract-symbol-index-periodic", daemon=True
        )
        self._periodic_thread.start()

    def stop(self, timeout: float | None = 5.0) -> None:
        """Signal every thread to exit and join them."""
        self._stop_event.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=timeout)
            finally:
                self._observer = None
        for thread in (self._debounce_thread, self._periodic_thread):
            if thread is not None:
                thread.join(timeout=timeout)
        self._debounce_thread = None
        self._periodic_thread = None
        # Flush anything still pending so a stop-then-inspect test path
        # sees the effect of any event that arrived just before stop.
        self._flush_pending()

    def __enter__(self) -> "SymbolIndexWatcher":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Event pipeline
    # ------------------------------------------------------------------

    def _accept_path(self, path: Path) -> bool:
        if path.suffix not in self.extensions:
            return False
        try:
            path.relative_to(self.root)
        except ValueError:
            return False
        return True

    def _queue_event(self, path: Path, deleted: bool) -> None:
        self.stats.events_seen += 1
        if not self._accept_path(path):
            return
        with self._pending_lock:
            self._pending[path] = time.monotonic() + (
                0.0 if deleted else self.debounce_seconds
            )
            self._pending_deleted[path] = deleted or self._pending_deleted.get(
                path, False
            )

    def _debounce_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=max(self.debounce_seconds / 2, 0.02))
            self._flush_pending()

    def _flush_pending(self) -> None:
        now = time.monotonic()
        to_process: list[tuple[Path, bool]] = []
        with self._pending_lock:
            due = [p for p, at in self._pending.items() if at <= now]
            for path in due:
                deleted = self._pending_deleted.pop(path, False)
                self._pending.pop(path, None)
                to_process.append((path, deleted))
        for path, deleted in to_process:
            try:
                if deleted or not path.exists():
                    self._reindex_delete(path)
                else:
                    self._reindex_write(path)
            except Exception as exc:  # pragma: no cover - defensive
                self.stats.parse_errors += 1
                LOG.warning("watcher failed on %s: %s", path, exc)

    def _reindex_write(self, path: Path) -> None:
        rows = parse_file(path)
        with self._index_lock:
            self.index.replace_file(str(path), rows)
        self.stats.reindex_calls += 1
        # v0.5.1 wiring module_08 (Lens E MEM-E-02) cascade: fresh
        # symbols are in the store; update the derived indexes so the
        # three-index snapshot stays consistent. Cascade errors do NOT
        # break the watcher: each helper's failure is logged, counted,
        # and the loop continues to the next attached index.
        self._cascade_write(path)

    def _reindex_delete(self, path: Path) -> None:
        with self._index_lock:
            self.index.delete_by_file(str(path))
        self.stats.delete_calls += 1
        self._cascade_delete(path)

    # ------------------------------------------------------------------
    # v0.5.1 wiring module_08 -- cascade to attached indexes + cache
    # ------------------------------------------------------------------

    def _cascade_write(self, path: Path) -> None:
        """Cascade a write event to graph, semantic, and cache handles.

        Each attached index updates independently; a raise in one does
        not skip the others. The cache invalidation runs LAST so a
        successful reader immediately following the cascade sees a
        miss and re-runs against the freshly-updated indexes.
        """
        path_str = str(path)
        # Graph index update.
        if self.graph_populator is not None:
            try:
                self.graph_populator.update_file(path)
                self.stats.graph_updates += 1
            except Exception as exc:  # noqa: BLE001 -- one index failing must not skip others
                self.stats.graph_errors += 1
                LOG.warning(
                    "watcher graph cascade failed on %s: %s", path_str, exc
                )
        # Semantic index update: walk the fresh symbols in this file
        # and call update_symbol per-symbol. Import inline to avoid a
        # module-load cycle with semantic_builder.
        if self.semantic_index is not None:
            try:
                from ract.memory.semantic_builder import (  # noqa: PLC0415
                    update_symbol as _semantic_update_symbol,
                )

                with self._index_lock:
                    file_syms = self.index.find_in_file(path_str)
                for row in file_syms:
                    sym_id = getattr(row, "id", None)
                    if sym_id is None:
                        continue
                    try:
                        _semantic_update_symbol(
                            int(sym_id), self.semantic_index, self.index
                        )
                    except Exception as exc:  # noqa: BLE001
                        self.stats.semantic_errors += 1
                        LOG.warning(
                            "watcher semantic cascade failed on %s (sym=%s): %s",
                            path_str,
                            sym_id,
                            exc,
                        )
                        continue
                self.stats.semantic_updates += 1
            except Exception as exc:  # noqa: BLE001 -- protect the watcher loop
                self.stats.semantic_errors += 1
                LOG.warning(
                    "watcher semantic cascade helper failed on %s: %s",
                    path_str,
                    exc,
                )
        # Cache invalidation LAST so a subsequent lookup sees a miss
        # after the underlying indexes have already been updated.
        if self.cache is not None:
            try:
                dropped = int(self.cache.invalidate_by_file(path_str) or 0)
                self.stats.cache_invalidations += dropped
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "watcher cache invalidation failed on %s: %s", path_str, exc
                )
        self._emit_freshness_gap(path_str, "write")

    def _cascade_delete(self, path: Path) -> None:
        """Cascade a delete event to graph, semantic, and cache handles."""
        path_str = str(path)
        if self.graph_populator is not None:
            try:
                graph = getattr(self.graph_populator, "_graph", None)
                if graph is not None:
                    graph.delete_by_source_file(path_str)
                    self.stats.graph_updates += 1
            except Exception as exc:  # noqa: BLE001
                self.stats.graph_errors += 1
                LOG.warning(
                    "watcher graph delete cascade failed on %s: %s",
                    path_str,
                    exc,
                )
        if self.semantic_index is not None:
            try:
                self.semantic_index.delete_by_file(path_str)
                self.stats.semantic_updates += 1
            except Exception as exc:  # noqa: BLE001
                self.stats.semantic_errors += 1
                LOG.warning(
                    "watcher semantic delete cascade failed on %s: %s",
                    path_str,
                    exc,
                )
        if self.cache is not None:
            try:
                dropped = int(self.cache.invalidate_by_file(path_str) or 0)
                self.stats.cache_invalidations += dropped
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "watcher cache invalidation (delete) failed on %s: %s",
                    path_str,
                    exc,
                )
        self._emit_freshness_gap(path_str, "delete")

    def _emit_freshness_gap(self, path_str: str, kind: str) -> None:
        """Emit ``memory.freshness_gap`` with the per-index attachment status.

        Best-effort: import guarded so a watcher wired without the
        trace-sink module keeps running silently. The event names
        which indexes are attached so an operator can spot a
        misconfigured watcher (e.g. semantic detached in production).
        """
        try:
            from ract.trace.sink import emit as _emit_event  # noqa: PLC0415

            _emit_event(
                "memory.freshness_gap",
                {
                    "path": path_str,
                    "kind": kind,
                    "cache_attached": self.cache is not None,
                    "graph_attached": self.graph_populator is not None,
                    "semantic_attached": self.semantic_index is not None,
                },
            )
        except Exception:  # noqa: BLE001 -- trace failures must not break the watcher
            pass

    # ------------------------------------------------------------------
    # Periodic scan fallback (Lateral Chain branch B)
    # ------------------------------------------------------------------

    def _periodic_loop(self) -> None:
        while not self._stop_event.wait(timeout=self.periodic_scan_seconds):
            try:
                self.run_periodic_scan()
            except Exception as exc:  # pragma: no cover - defensive
                LOG.warning("periodic scan failed: %s", exc)

    def run_periodic_scan(self) -> int:
        """Compare filesystem mtime against stored ``updated_at``; reindex diffs.

        Returns the number of files re-indexed on this pass.

        v0.5.1 wiring module_08 (Lens E MEM-E-01) closure: the scan
        also calls :meth:`RetrievalCache.invalidate_expired` when a
        cache is attached so a long-idle process still ages TTL rows
        even when no source change fires.
        """
        self.stats.periodic_scans += 1
        # TTL sweep on the retrieval cache runs each tick so an idle
        # process (no source changes) still enforces the age limit.
        if self.cache is not None:
            try:
                evicted = int(self.cache.invalidate_expired() or 0)
                self.stats.ttl_evictions += evicted
            except Exception as exc:  # noqa: BLE001
                LOG.warning("watcher cache TTL sweep failed: %s", exc)
        with self._index_lock:
            stored = self.index.file_mtimes()
        reindexed = 0
        for path_str, stored_mtime in stored.items():
            path = Path(path_str)
            if not path.exists():
                self._reindex_delete(path)
                reindexed += 1
                continue
            try:
                current = int(path.stat().st_mtime)
            except OSError:
                continue
            if current > stored_mtime:
                try:
                    self._reindex_write(path)
                    reindexed += 1
                except Exception as exc:  # pragma: no cover - defensive
                    self.stats.parse_errors += 1
                    LOG.warning("periodic reindex failed on %s: %s", path, exc)
        return reindexed

    def flush(self) -> None:
        """Force the debouncer to process every pending event immediately.

        Test hook: after writing a file and calling ``flush``, the
        index reflects the write without waiting for the debounce
        window.
        """
        with self._pending_lock:
            for path in list(self._pending):
                self._pending[path] = time.monotonic() - 1.0
        self._flush_pending()


class _EventHandler(FileSystemEventHandler):
    """Watchdog-side glue that pushes into :class:`SymbolIndexWatcher`."""

    def __init__(self, parent: SymbolIndexWatcher) -> None:
        super().__init__()
        self._parent = parent

    def _dispatch(self, event: FileSystemEvent, deleted: bool) -> None:
        if event.is_directory:
            return
        raw_path = getattr(event, "src_path", None)
        if raw_path is None:
            return
        path = Path(raw_path)
        self._parent._queue_event(path, deleted)

    def on_created(self, event: FileSystemEvent) -> None:
        self._dispatch(event, deleted=False)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._dispatch(event, deleted=False)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._dispatch(event, deleted=True)

    def on_moved(self, event: FileSystemEvent) -> None:
        # A rename is a delete of the src plus a write of the dest.
        raw_src = getattr(event, "src_path", None)
        raw_dest = getattr(event, "dest_path", None)
        if raw_src is not None:
            self._parent._queue_event(Path(raw_src), deleted=True)
        if raw_dest is not None:
            self._parent._queue_event(Path(raw_dest), deleted=False)


__all__ = [
    "SymbolIndexWatcher",
    "WatcherStats",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
