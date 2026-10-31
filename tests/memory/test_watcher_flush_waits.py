"""flush() returns only after a batch the watcher thread already took is indexed."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ract.memory.symbol_index import SymbolIndex
from ract.memory.watcher import SymbolIndexWatcher


def test_flush_waits_for_the_batch_in_progress(tmp_path: Path) -> None:
    with SymbolIndex() as idx:
        watcher = SymbolIndexWatcher(tmp_path, idx, debounce_seconds=0.01)
        p = tmp_path / "slow.py"
        p.write_text("def slow():\n    return 1\n", encoding="utf-8")
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        real = watcher._reindex_write

        def slow_reindex(path: Path) -> None:
            started.set()
            release.wait(5)
            real(path)
            done.set()

        watcher._reindex_write = slow_reindex  # type: ignore[method-assign]
        watcher._queue_event(p, deleted=False)
        with watcher._pending_lock:
            watcher._pending[p] = time.monotonic() - 1.0
        background = threading.Thread(target=watcher._flush_pending)
        background.start()  # the watcher's own thread, mid-batch
        assert started.wait(5)
        flushed = threading.Event()
        caller = threading.Thread(target=lambda: (watcher.flush(), flushed.set()))
        caller.start()
        assert not flushed.wait(0.3), "flush() returned while the batch was in progress"
        release.set()
        caller.join(5)
        background.join(5)
        assert flushed.is_set() and done.is_set()
        assert any(r.name == "slow" for r in idx.find_in_file(str(p)))
