"""File-watcher tests for the symbol index.

The watchdog observer's delivery latency is platform-dependent (fast
on Linux inotify, slower on Windows ReadDirectoryChangesW), so tests
rely on the debouncer's :meth:`SymbolIndexWatcher.flush` hook to
force pending events through synchronously. Independent periodic-scan
coverage lives in :func:`test_periodic_scan_reindexes_stale_mtime`
which does not depend on watchdog delivery.
"""

from __future__ import annotations

import time
from pathlib import Path

from ract.memory.symbol_index import SymbolIndex
from ract.memory.watcher import SymbolIndexWatcher


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _wait_for(
    predicate,
    *,
    timeout: float = 3.0,
    tick: float = 0.05,
    watcher: SymbolIndexWatcher | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if watcher is not None:
            watcher.flush()
        if predicate():
            return True
        time.sleep(tick)
    if watcher is not None:
        watcher.flush()
    return predicate()


# ---------------------------------------------------------------------------
# Event pipeline
# ---------------------------------------------------------------------------


def test_watcher_indexes_new_file(tmp_path: Path) -> None:
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.05)
        with watcher:
            new = tmp_path / "new.py"
            _write(new, "def hello():\n    return 42\n")
            assert _wait_for(
                lambda: any(r.name == "hello" for r in idx.find_in_file(str(new))),
                watcher=watcher,
            )


def test_watcher_reindexes_modified_file(tmp_path: Path) -> None:
    file_path = tmp_path / "mod.py"
    _write(file_path, "def one():\n    pass\n")
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.05)
        with watcher:
            watcher._reindex_write(file_path)  # seed the store
            _write(file_path, "def one():\n    pass\n\ndef two():\n    pass\n")
            assert _wait_for(
                lambda: (
                    {r.name for r in idx.find_in_file(str(file_path))} == {"one", "two"}
                ),
                watcher=watcher,
            )


def test_watcher_deletes_removed_file(tmp_path: Path) -> None:
    file_path = tmp_path / "ephemeral.py"
    _write(file_path, "def gone():\n    pass\n")
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.05)
        with watcher:
            watcher._reindex_write(file_path)
            assert idx.find_in_file(str(file_path))
            file_path.unlink()
            assert _wait_for(
                lambda: idx.find_in_file(str(file_path)) == [],
                watcher=watcher,
            )


def test_watcher_ignores_unrelated_extension(tmp_path: Path) -> None:
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.05)
        with watcher:
            _write(tmp_path / "readme.md", "not source")
            time.sleep(0.2)
            watcher.flush()
            assert idx.count() == 0


# ---------------------------------------------------------------------------
# Periodic-scan fallback (Lateral Chain branch B)
# ---------------------------------------------------------------------------


def test_periodic_scan_reindexes_stale_mtime(tmp_path: Path) -> None:
    file_path = tmp_path / "drift.py"
    _write(file_path, "def one():\n    pass\n")
    with SymbolIndex() as idx:
        # Configure the watcher with a very long periodic-scan window
        # so the test drives the scan by hand rather than waiting for
        # the daemon thread.
        watcher = SymbolIndexWatcher(
            tmp_path, idx, debounce_seconds=0.05, periodic_scan_seconds=10_000
        )
        # Seed the index without starting watchdog — the periodic scan
        # is the ONLY invalidation path in this test.
        watcher._reindex_write(file_path)
        assert {r.name for r in idx.find_in_file(str(file_path))} == {"one"}
        # Rewrite the file with a mtime known to be strictly newer.
        _write(file_path, "def one():\n    pass\n\ndef two():\n    pass\n")
        future = int(time.time()) + 10
        import os

        os.utime(file_path, (future, future))
        reindexed = watcher.run_periodic_scan()
        assert reindexed >= 1
        assert {r.name for r in idx.find_in_file(str(file_path))} == {"one", "two"}


def test_periodic_scan_deletes_missing_file(tmp_path: Path) -> None:
    file_path = tmp_path / "vanish.py"
    _write(file_path, "def gone():\n    pass\n")
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(
            tmp_path, idx, debounce_seconds=0.05, periodic_scan_seconds=10_000
        )
        watcher._reindex_write(file_path)
        assert idx.count() == 1
        file_path.unlink()
        watcher.run_periodic_scan()
        assert idx.count() == 0


def test_periodic_scan_runs_on_independent_thread(tmp_path: Path) -> None:
    # Second Pass Q3: the periodic-scan fallback must not share a
    # thread with the watchdog event stream. Verify by starting the
    # watcher and asserting the observer, debounce, and periodic
    # threads are three distinct objects.
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, periodic_scan_seconds=10_000)
        watcher.start()
        try:
            assert watcher._periodic_thread is not None
            assert watcher._debounce_thread is not None
            assert watcher._periodic_thread is not watcher._debounce_thread
            assert watcher._periodic_thread.is_alive()
        finally:
            watcher.stop()


def test_watcher_start_and_stop_are_idempotent(tmp_path: Path) -> None:
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx)
        watcher.start()
        watcher.start()  # second start is a no-op
        watcher.stop()
        watcher.stop()  # second stop is a no-op
