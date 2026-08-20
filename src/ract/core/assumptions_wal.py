"""Crash-consistency WAL for :class:`AssumptionRegistry` (module_01 of v0.5.1).

DEEPSEEK_REVIEW_5 §"G1 deeper dive" (triple-triangulated with REVIEW_2
criticism 2 and REVIEW_4 G1) identified that ``AssumptionRegistry`` was
a Python dict that only persisted in ``__exit__``. On an OS kill mid-run
(compaction #117 of a 200-compaction chain) the entire assumption graph
was lost — RK-1.5 (assumption must be registered) then failed for every
prior artifact, forcing the model to either discard all prior work or
accept unverified artifacts. Either outcome is the drift the loop is
meant to prevent.

This module adds a write-ahead log so every state transition
(``proposed`` / ``accepted`` / ``discharged`` / ``violated``) hits disk
with ``fsync`` before the in-memory mutation. On reload the registry
replays a snapshot-plus-tail scheme:

    snapshot: ``.ract/assumptions.json``  — periodic full dump.
    tail:     ``.ract/assumptions.wal``   — JSONL of transitions since
                                             snapshot; one line per
                                             transition; ``fsync`` per
                                             append.

``rotate_snapshot()`` writes the current in-memory state atomically via
``os.replace`` and truncates the WAL. Both operations happen under the
same cross-platform exclusive lock, so a concurrent writer cannot
inject a WAL line between snapshot-capture and WAL-truncate.

The lock dispatches on ``sys.platform``: ``msvcrt.locking`` on Windows,
``fcntl.flock`` on POSIX. Both branches lock the same 1-byte range at
offset 0 so semantics match at the "one writer at a time" level.
Advisory-vs-mandatory difference is documented but does not affect
correctness for the cooperating-RACT-processes case this module targets.

Ordering invariant (Lateral branch E in the module_01 fragment):
``append → fsync → mutate → emit``. A failed emit does not corrupt WAL
state — replay reconstructs identical registry state; a missed event is
a trace-log gap, not a state gap. This is an intentional
durability-over-trace-completeness trade-off.

Reference:
- ``_BUILD/ract_v0.5.1_external_review/DEEPSEEK_REVIEW_5.md`` §G1.
- ``_BUILD/ract_v0.5.1_external_review_response/module_01.md``.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ContextManager

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WalLockContended(RuntimeError):
    """Raised when the WAL file lock cannot be acquired after retries.

    A concurrent RACT process on the same tree already holds the WAL
    lock and did not release within the retry window
    (:func:`_LOCK_RETRIES` attempts, :data:`_LOCK_BACKOFF_S` seconds
    each). Caller sees an explicit failure — never a silent overwrite.
    """


class WalCorruptError(RuntimeError):
    """Raised when a middle WAL line is malformed on replay.

    A malformed *tail* line (truncated by a process kill) is tolerated
    with a WARN; the truncated tail is skipped and replay stops. A
    malformed *middle* line implies non-append corruption (something
    other than crash mid-write) and is not tolerable — replay refuses
    to guess.
    """


# ---------------------------------------------------------------------------
# Cross-platform file lock
# ---------------------------------------------------------------------------


# Retry policy for the exclusive byte-range lock. Three attempts with
# 10ms between them is enough for cooperative RACT processes to yield
# after their own transition completes; longer waits would mask a real
# hang.
_LOCK_RETRIES = 3
_LOCK_BACKOFF_S = 0.01


# ``O_BINARY`` exists on Windows only. Adding it prevents the CRT
# text-mode layer from translating ``\n`` into ``\r\n`` on write and
# from stripping ``\r`` from lines on read. The WAL is a byte-exact
# JSONL stream on every OS.
_BINARY_FLAG = getattr(os, "O_BINARY", 0)
_WAL_OPEN_FLAGS_APPEND = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _BINARY_FLAG
_WAL_OPEN_FLAGS_TRUNC = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY_FLAG


if sys.platform == "win32":
    import msvcrt  # type: ignore[import-not-found]

    def _lock_exclusive(fd: int) -> None:
        """Acquire an exclusive lock on the first byte of ``fd``.

        ``msvcrt.locking`` locks a mandatory byte range (Windows). The
        loop retries a bounded number of times; on failure it raises
        :class:`WalLockContended`.
        """
        # msvcrt requires seeking to the byte we want to lock.
        cur = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            for attempt in range(_LOCK_RETRIES):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    if attempt == _LOCK_RETRIES - 1:
                        raise WalLockContended(
                            "assumptions.wal is locked by another RACT process; "
                            f"gave up after {_LOCK_RETRIES} attempts"
                        )
                    time.sleep(_LOCK_BACKOFF_S)
        finally:
            os.lseek(fd, cur, os.SEEK_SET)

    def _unlock(fd: int) -> None:
        """Release the lock previously held on the first byte of ``fd``."""
        cur = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                # Lock may have been released already; treat as no-op.
                pass
        finally:
            os.lseek(fd, cur, os.SEEK_SET)

else:
    import fcntl  # type: ignore[import-not-found]

    def _lock_exclusive(fd: int) -> None:
        """Acquire an exclusive advisory lock on ``fd`` (POSIX)."""
        for attempt in range(_LOCK_RETRIES):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if attempt == _LOCK_RETRIES - 1:
                    raise WalLockContended(
                        "assumptions.wal is locked by another RACT process; "
                        f"gave up after {_LOCK_RETRIES} attempts"
                    )
                time.sleep(_LOCK_BACKOFF_S)

    def _unlock(fd: int) -> None:
        """Release the advisory lock previously held on ``fd``."""
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Canonical JSONL line
# ---------------------------------------------------------------------------


def _canonical_line(payload: dict[str, Any]) -> bytes:
    """Return one canonical JSONL line for ``payload``.

    Keys are sorted; separators are compact; UTF-8; trailing newline.
    Stable across Python builds so replay of a WAL written by one
    process is byte-identical to what a re-serialisation of the same
    payload would produce.
    """
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# WAL entry vocabulary
# ---------------------------------------------------------------------------


# The four transitions the registry logs. Kept as a module-level tuple
# so callers (registry + tests) share a single vocabulary; adding a new
# transition without extending this list is a review-visible signal.
TRANSITIONS: tuple[str, ...] = ("proposed", "accepted", "discharged", "violated")


@dataclass(frozen=True)
class WalEntry:
    """One parsed WAL line.

    ``kind`` is one of :data:`TRANSITIONS`. ``payload`` is the raw
    per-transition body; the registry reload path maps it back onto
    :class:`ract.core.assumption.Assumption` state.
    """

    kind: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# WAL store — the on-disk artifact this module owns
# ---------------------------------------------------------------------------


class AssumptionWal:
    """On-disk snapshot-plus-WAL store for :class:`AssumptionRegistry`.

    The store owns two files inside ``wal_dir``:

    - ``assumptions.json`` — canonical snapshot of the registry state at
      the last rotation. On first construction it may be absent.
    - ``assumptions.wal`` — append-only JSONL tail of every transition
      since the snapshot. On first construction it may be absent.

    The store never mutates the in-memory registry; it just persists
    and replays transitions. The registry is responsible for calling
    :meth:`append` before its own mutation and reconstructing state
    from :meth:`load_all`.
    """

    SNAPSHOT_NAME = "assumptions.json"
    WAL_NAME = "assumptions.wal"

    def __init__(self, wal_dir: Path) -> None:
        self._wal_dir = Path(wal_dir)
        self._wal_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_path = self._wal_dir / self.SNAPSHOT_NAME
        self._wal_path = self._wal_dir / self.WAL_NAME
        # In-process serialisation. The OS file lock covers
        # cross-process safety; this threading lock covers thread-vs-
        # thread contention inside one Python process. Without it, on
        # Windows the mandatory ``msvcrt.locking`` lock would trip
        # ``WalLockContended`` under GIL-unfair scheduling before the
        # first thread had a chance to release.
        self._thread_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Paths (test hooks)
    # ------------------------------------------------------------------

    @property
    def snapshot_path(self) -> Path:
        """Path to the ``assumptions.json`` snapshot."""
        return self._snapshot_path

    @property
    def wal_path(self) -> Path:
        """Path to the ``assumptions.wal`` tail."""
        return self._wal_path

    # ------------------------------------------------------------------
    # Load path
    # ------------------------------------------------------------------

    def load_all(self) -> tuple[list[WalEntry], list[WalEntry]]:
        """Return ``(snapshot_entries, wal_entries)`` for a full replay.

        Snapshot entries are the JSONL lines of the current snapshot
        (empty list if no snapshot has ever been written). WAL entries
        are every transition since the snapshot, in append order.

        Malformed *middle* WAL lines raise :class:`WalCorruptError`.
        A malformed *tail* line (partial write, kill-during-append) is
        skipped with no error — replay stops at the last good line and
        the caller can continue as if the truncated transition never
        happened. This preserves the append→fsync→mutate ordering: the
        mutation had not yet reached memory when the process died.
        """
        snapshot_entries = self._read_lines(self._snapshot_path, tolerate_tail=False)
        wal_entries = self._read_lines(self._wal_path, tolerate_tail=True)
        return snapshot_entries, wal_entries

    @staticmethod
    def _read_lines(path: Path, *, tolerate_tail: bool) -> list[WalEntry]:
        if not path.exists():
            return []
        raw = path.read_bytes()
        if not raw:
            return []
        # Splitlines with keepends=False is safe here because canonical
        # lines are ASCII-JSON terminated by ``\n``; ``splitlines`` does
        # NOT split on CR-only inside a UTF-8 JSON body (there are no
        # bare CRs there).
        text = raw.decode("utf-8", errors="strict")
        lines = text.split("\n")
        # A well-formed file ends in a trailing ``\n``, giving an empty
        # last element from split; strip it.
        if lines and lines[-1] == "":
            lines.pop()
        out: list[WalEntry] = []
        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                if tolerate_tail and i == len(lines) - 1:
                    # Truncated tail — a process kill mid-append. Skip
                    # silently: the mutation never reached memory.
                    break
                raise WalCorruptError(
                    f"malformed WAL line {i} in {path}: {exc}"
                ) from exc
            kind = obj.get("kind")
            if kind not in TRANSITIONS:
                raise WalCorruptError(
                    f"unknown transition kind {kind!r} at line {i} in {path}"
                )
            out.append(WalEntry(kind=kind, payload=obj))
        return out

    # ------------------------------------------------------------------
    # Append path
    # ------------------------------------------------------------------

    def append(self, kind: str, payload: dict[str, Any]) -> None:
        """Append one transition line to the WAL, fsync, then return.

        Held for the duration of the append: an exclusive lock on the
        WAL file's byte-0. Any concurrent RACT process attempting the
        same append will retry a bounded number of times, then raise
        :class:`WalLockContended`.

        Ordering invariant: this method returns only after ``fsync``
        completes. The caller then mutates its in-memory state.
        """
        if kind not in TRANSITIONS:
            raise ValueError(f"unknown transition kind {kind!r}")
        line = _canonical_line({**payload, "kind": kind})
        # ``os.O_APPEND`` guarantees each ``write`` is atomic with
        # respect to file position on POSIX; on Windows the exclusive
        # byte-lock enforces serialisation. Together they prevent
        # interleaved partial lines from concurrent writers. On
        # Windows we also add ``O_BINARY`` so ``\n`` is not translated
        # to ``\r\n`` by the CRT text-mode layer — the WAL is a
        # byte-exact JSONL stream on every OS.
        with self._thread_lock:
            fd = os.open(
                self._wal_path,
                _WAL_OPEN_FLAGS_APPEND,
                0o644,
            )
            try:
                _lock_exclusive(fd)
                try:
                    os.write(fd, line)
                    os.fsync(fd)
                finally:
                    _unlock(fd)
            finally:
                os.close(fd)

    # ------------------------------------------------------------------
    # Rotation — snapshot + WAL truncate
    # ------------------------------------------------------------------

    def rotate_snapshot(self, snapshot_entries: list[dict[str, Any]]) -> None:
        """Write ``snapshot_entries`` as a new snapshot and truncate WAL.

        ``snapshot_entries`` are already-canonical per-assumption
        dictionaries (each carrying its own ``kind`` field — typically
        the terminal kind for that assumption, or ``"proposed"`` for a
        never-accepted one). They are written as JSONL so replay can
        use the same parser as the WAL.

        The full sequence:

        1. Write ``assumptions.json.tmp`` with all entries + ``fsync``.
        2. ``os.replace(tmp, assumptions.json)`` — atomic rename.
        3. Truncate ``assumptions.wal`` to zero bytes + ``fsync``.

        Steps 1-3 happen inside the WAL byte-0 lock so no concurrent
        writer can inject a line between snapshot-capture and
        WAL-truncate. A kill during any step leaves either
        (old snapshot + non-empty WAL) or (new snapshot + empty WAL)
        recoverable — never a torn pair.
        """
        tmp_path = self._snapshot_path.with_suffix(".json.tmp")
        # Serialize the snapshot body first so a bad payload raises
        # BEFORE we take the lock.
        body = b"".join(
            _canonical_line({**entry, "kind": entry.get("kind", "proposed")})
            for entry in snapshot_entries
        )
        # Open the WAL lock file to serialise across writers. The
        # in-process threading lock parallels the file lock (see
        # ``append`` for the same pattern).
        self._thread_lock.acquire()
        lock_fd = os.open(
            self._wal_path,
            _WAL_OPEN_FLAGS_APPEND,
            0o644,
        )
        try:
            _lock_exclusive(lock_fd)
            try:
                # 1. Snapshot to tmp + fsync.
                snap_fd = os.open(
                    tmp_path,
                    _WAL_OPEN_FLAGS_TRUNC,
                    0o644,
                )
                try:
                    if body:
                        os.write(snap_fd, body)
                    os.fsync(snap_fd)
                finally:
                    os.close(snap_fd)
                # 2. Atomic rename tmp -> snapshot. ``os.replace``
                # overwrites cleanly on both POSIX and Windows.
                os.replace(tmp_path, self._snapshot_path)
                # 3. Truncate WAL under the same lock. We already hold
                # ``lock_fd`` open; truncate it and fsync.
                os.ftruncate(lock_fd, 0)
                os.fsync(lock_fd)
            finally:
                _unlock(lock_fd)
        finally:
            os.close(lock_fd)
            self._thread_lock.release()


# ---------------------------------------------------------------------------
# Test hook: a context manager for callers that want to serialise a
# tight sequence of appends under one lock hold. Not used by the
# registry today; kept for future compaction-batching.
# ---------------------------------------------------------------------------


class _WalLockHold:
    """Context manager: hold the WAL exclusive lock across a block."""

    def __init__(self, wal: AssumptionWal) -> None:
        self._wal = wal
        self._fd: int | None = None

    def __enter__(self) -> "_WalLockHold":
        self._fd = os.open(
            self._wal.wal_path,
            _WAL_OPEN_FLAGS_APPEND,
            0o644,
        )
        _lock_exclusive(self._fd)
        return self

    def __exit__(self, *args: object) -> None:
        assert self._fd is not None
        try:
            _unlock(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None


def lock_hold(wal: AssumptionWal) -> ContextManager["_WalLockHold"]:
    """Return a context manager that holds ``wal``'s exclusive lock."""
    return _WalLockHold(wal)


# RACT 0.5.1
