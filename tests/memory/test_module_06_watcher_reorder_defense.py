"""v0.5.2 hardening module_06 -- DA-B F-5.4 on_moved reorder race.

Master spec: ``docs/RACT_v0.5.2_HARDENING_SPEC.md`` §5 module_06.
DA-B finding: ``_BUILD/audit_2026-08-22b/DA_B_runtime_trace_memory.md``
F-5.4 (MED) -- on_moved src-delete + dest-create pair can arrive
out of order on network shares. If ``deleted=True`` is enqueued
for a path that IS present at flush time (rename reversed, dest-
create then src-delete reordering, VSCode-style A -> A.tmp -> A
atomic-write cycles), invalidating on the flag would drop the
freshly-written entry -> stale cache-miss window.

Fix under test: ``_flush_pending`` decides delete-vs-write from
the file's actual existence at flush time, not the enqueued flag.
"""

from __future__ import annotations

from pathlib import Path

from ract.memory.symbol_index import SymbolIndex
from ract.memory.watcher import SymbolIndexWatcher


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_delete_flag_but_file_exists_is_reindexed_as_write(
    tmp_path: Path,
) -> None:
    """The heart of F-5.4: a reordered on_moved queues delete on
    a path that IS present -- must re-index as write, not delete.
    """
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.01)
        # Populate the file BEFORE starting the watcher so we start
        # from a known-indexed baseline.
        target = tmp_path / "keeper.py"
        _write(target, "def keeper():\n    return 1\n")
        with watcher:
            # Force initial index build by enqueueing a write.
            watcher._queue_event(target, deleted=False)
            watcher.flush()
            baseline = [r for r in idx.find_in_file(str(target))]
            assert any(r.name == "keeper" for r in baseline)

            # Simulate the reordered-on_moved bug: queue the delete
            # for a path that still exists on disk.
            watcher._queue_event(target, deleted=True)
            watcher.flush()

            # With the pre-fix behaviour, the delete flag wins and
            # the row is gone. With the F-5.4 fix, the actual disk
            # existence wins and the file is re-indexed.
            after = [r for r in idx.find_in_file(str(target))]
            assert any(r.name == "keeper" for r in after), (
                "F-5.4 regression: delete_flag=True on an existing "
                "file wiped the index entry; the fix should have "
                "re-indexed as a write instead."
            )


def test_write_flag_but_file_absent_is_reindexed_as_delete(
    tmp_path: Path,
) -> None:
    """Complementary invariant: enqueued write on a vanished path
    must fall through to delete rather than raise a parse error.
    """
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.01)
        ghost = tmp_path / "ghost.py"
        _write(ghost, "def ghost():\n    return 0\n")
        with watcher:
            watcher._queue_event(ghost, deleted=False)
            watcher.flush()
            assert any(r.name == "ghost" for r in idx.find_in_file(str(ghost)))

            ghost.unlink()
            # Enqueue a WRITE (deleted=False) for the vanished path.
            watcher._queue_event(ghost, deleted=False)
            watcher.flush()

            assert not any(r.name == "ghost" for r in idx.find_in_file(str(ghost))), (
                "F-5.4 companion: write_flag=False on a vanished "
                "file should fall through to delete_reindex; the "
                "stale row survived."
            )


def test_normal_delete_still_removes_row(tmp_path: Path) -> None:
    """Sanity: the fix must not regress the normal delete path."""
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.01)
        p = tmp_path / "normal.py"
        _write(p, "def normal():\n    return 2\n")
        with watcher:
            watcher._queue_event(p, deleted=False)
            watcher.flush()
            assert any(r.name == "normal" for r in idx.find_in_file(str(p)))
            p.unlink()
            watcher._queue_event(p, deleted=True)
            watcher.flush()
            assert not any(r.name == "normal" for r in idx.find_in_file(str(p)))


def test_normal_write_still_indexes(tmp_path: Path) -> None:
    """Sanity: the fix must not regress the normal write path."""
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.01)
        with watcher:
            p = tmp_path / "fresh.py"
            _write(p, "def fresh():\n    return 3\n")
            watcher._queue_event(p, deleted=False)
            watcher.flush()
            assert any(r.name == "fresh" for r in idx.find_in_file(str(p)))
