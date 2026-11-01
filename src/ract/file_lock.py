"""One exclusive file lock for RACT's state files (B-207).

LR:: The same lock was copied into the assumption WAL, the suite chain, the
workspace digest chain, the manifest ledger and the run marker; the run
marker's copy went on without the lock after its tries. Each caller now names
its own error, and every copy shares this one behaviour: the first byte of the
file, a bounded number of non-blocking tries with a short pause, and then the
caller's error. ``msvcrt.locking`` on Windows locks a byte range at the current
position, so the position is moved to 0 and put back.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

if sys.platform == "win32":
    import msvcrt  # type: ignore[import-not-found]
else:
    import fcntl  # type: ignore[import-not-found,unused-ignore]


def _try_lock(fd: int) -> None:
    if sys.platform == "win32":
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]


def lock_exclusive(
    fd: int,
    *,
    contended: Callable[[int], BaseException],
    retries: int = 3,
    backoff_s: float = 0.01,
) -> None:
    """Take the lock on *fd*, or raise ``contended(retries)`` after *retries* tries."""
    cur = os.lseek(fd, 0, os.SEEK_CUR) if sys.platform == "win32" else 0
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
    try:
        for attempt in range(retries):
            try:
                _try_lock(fd)
                return
            except OSError:
                if attempt == retries - 1:
                    raise contended(retries) from None
                time.sleep(backoff_s)
    finally:
        if sys.platform == "win32":
            os.lseek(fd, cur, os.SEEK_SET)


def unlock(fd: int, *, what: str = "a state file") -> None:
    """Release the lock on *fd*; a lock already gone is reported, not raised."""
    cur = os.lseek(fd, 0, os.SEEK_CUR) if sys.platform == "win32" else 0
    try:
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
    except OSError as exc:
        print(f"[lock] the lock on {what} was not released: {exc}", flush=True)
    finally:
        if sys.platform == "win32":
            os.lseek(fd, cur, os.SEEK_SET)


__all__ = ["lock_exclusive", "unlock"]
