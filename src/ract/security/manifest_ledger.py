"""Historical Manifest Ledger for RK-3 durability (v0.5.1 module_07).

DEEPSEEK_REVIEW_3 C1 (triple-triangulated with REVIEW_4_UNKNOWN B2 + D1
and REVIEW_5 §"Historical Manifest Ledger") identified that the
CapabilityManifest was signed into the RK-3 environment attestation but
was itself ephemeral: nothing on disk recorded WHICH manifest was in
force at the moment each Rootknot was signed. When the operator later
edits the manifest (adds a required binary, tightens a filesystem rule),
every historical Rootknot's ``manifest_digest`` field points into the
void. ``ract verify`` cannot say "at signing time this artifact was
authorized" -- only "this artifact does not match TODAY's manifest".

This module writes the missing record. Every RK-3 environment
attestation appends one entry to ``.ract/manifest_ledger.jsonl``. Each
entry cross-references:

- the manifest_digest observed (32-byte SHA-256 hex);
- the full canonical manifest bytes, stored content-addressably at
  ``.ract/manifest_snapshots/{digest_hex}.json`` (dedup: many entries
  reference one snapshot file);
- the RK-3 environment_signature that observed this manifest;
- the Rootknot's run_id (32-hex; module_06 propagation);
- a bounded ``tool_trace_summary`` (which tools ran, count,
  first/last invocation timestamps);
- a Merkle tail: ``prev_ledger_hash`` is the SHA-256 of the prior
  entry's canonical JSON bytes (or the sentinel ``"GENESIS"`` for the
  first entry). A bit-flip anywhere in the middle surfaces as a
  ``verify_chain`` break at the mutated index.
- a WAL cross-link (``first_wal_seq`` / ``last_wal_seq``) recording
  the RootknotWAL line count observed at ledger append time. This lets
  audit tooling join "what assumptions were active" to "what manifest
  was signed".

The ledger is an OBSERVER, not part of the signed RK-3 payload. The
sacred spine (three-signature schema) is unchanged. A ledger corruption
does not invalidate any Rootknot signature; it only weakens the
historical-manifest attestation surface. Conversely, a Rootknot with a
missing ledger entry still verifies under RK-1/RK-2/RK-3 -- the ledger
adds a NEW verification surface ("manifest was authorised at signing
time") without replacing any existing one.

Cross-platform file lock mirrors ``ract.core.assumptions_wal``: an
exclusive byte-range lock on the first byte of the ledger file,
``msvcrt.locking`` on Windows and ``fcntl.flock`` on POSIX. The
``O_BINARY`` flag on Windows preserves byte-exact JSONL framing.

Merkle proof API (``proof_of``) walks the chain from a given entry
index to the tail, returning the hashes an offline verifier needs to
reconstruct "this manifest was seen at this position" without loading
the whole ledger.

Ambient-ledger accessor (module_06 pattern): ``bind_ledger`` binds a
:class:`ManifestLedger` for the run scope; ``get_current_ledger``
returns it. :meth:`Rootknot.attest_environment` consults the ambient
after signing and records the observation. Callers can also pass a
ledger explicitly via :func:`record_environment_attestation`.

Reference:
- ``_BUILD/ract_v0.5.1_external_review/DEEPSEEK_REVIEW_3.md`` §C1.
- ``_BUILD/ract_v0.5.1_external_review/REVIEW_4_UNKNOWN_REVIEWER.md``
  §B2 + §D1.
- ``_BUILD/ract_v0.5.1_external_review_response/module_07.md``.
- ``src/ract/core/assumptions_wal.py`` for the WAL-lock pattern this
  module mirrors.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ract.canonical import dumps_jcs
from ract.core.module_identity import _module_knot, register_module_knot

_LOG = logging.getLogger("ract.security.manifest_ledger")

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LedgerLockContended(RuntimeError):
    """Raised when the ledger file lock cannot be acquired after retries.

    A concurrent RACT process on the same ``.ract/`` directory already
    holds the ledger lock and did not release within the retry window.
    Caller sees an explicit failure -- never a silent overwrite.
    """


class LedgerCorruptError(RuntimeError):
    """Raised when a middle ledger line is malformed on replay.

    A malformed *tail* line (truncated by a process kill mid-append) is
    tolerated with a WARN; the truncated tail is skipped and iteration
    stops. A malformed *middle* line implies non-append corruption and
    is not tolerable -- readers refuse to guess.
    """


class LedgerSnapshotMissingError(RuntimeError):
    """Raised when a caller requests the manifest bytes for a digest not
    stored in the content-addressable snapshot dir.

    The ledger entry itself is not corrupt; the snapshot file simply
    was not written (or was manually removed). The caller can still
    verify the ledger chain -- only the manifest-body inspection surface
    is degraded.
    """


# ---------------------------------------------------------------------------
# Cross-platform file lock (mirrors ract.core.assumptions_wal)
# ---------------------------------------------------------------------------


# Retry policy for the exclusive byte-range lock. Three attempts with
# 10ms between them matches the WAL discipline -- cooperative RACT
# processes yield after their own append completes; longer waits would
# mask a real hang.
_LOCK_RETRIES = 3
_LOCK_BACKOFF_S = 0.01


# ``O_BINARY`` exists on Windows only. Adding it prevents the CRT
# text-mode layer from translating ``\n`` into ``\r\n`` on write and
# from stripping ``\r`` from lines on read. The ledger is a byte-exact
# JSONL stream on every OS.
_BINARY_FLAG = getattr(os, "O_BINARY", 0)
_LEDGER_OPEN_FLAGS_APPEND = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _BINARY_FLAG
# The append+dedup path opens ``RDWR`` because Windows ``msvcrt.locking``
# is mandatory -- a second handle opened for read would fail under the
# held lock. Reading tail bytes through the same locked fd sidesteps
# that. ``O_APPEND`` on the write side keeps concurrent-writer atomicity
# on POSIX; on Windows the exclusive byte-lock enforces serialisation.
_LEDGER_OPEN_FLAGS_RDWR = os.O_RDWR | os.O_CREAT | os.O_APPEND | _BINARY_FLAG


if sys.platform == "win32":
    import msvcrt  # type: ignore[import-not-found]

    def _lock_exclusive(fd: int) -> None:
        """Acquire an exclusive lock on the first byte of ``fd`` (Windows)."""
        cur = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            for attempt in range(_LOCK_RETRIES):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    if attempt == _LOCK_RETRIES - 1:
                        raise LedgerLockContended(
                            "manifest_ledger.jsonl is locked by another RACT "
                            f"process; gave up after {_LOCK_RETRIES} attempts"
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
                    raise LedgerLockContended(
                        "manifest_ledger.jsonl is locked by another RACT "
                        f"process; gave up after {_LOCK_RETRIES} attempts"
                    )
                time.sleep(_LOCK_BACKOFF_S)

    def _unlock(fd: int) -> None:
        """Release the advisory lock previously held on ``fd``."""
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Canonical helpers
# ---------------------------------------------------------------------------


# Sentinel for the first entry's prev_ledger_hash. The literal string
# ``"GENESIS"`` (not a zero-hash) is chosen for two reasons:
#   (i) a zero-hash could accidentally collide with a legitimate SHA-256
#       of some canonical entry (astronomically unlikely, but the
#       literal is unambiguous);
#   (ii) a human reader inspecting the JSONL immediately sees which
#        entry is first.
GENESIS = "GENESIS"


def _canonical_line(payload: dict[str, Any]) -> bytes:
    """Return one canonical JSONL line for ``payload``.

    JCS (RFC 8785, module_03) canonicalization. The trailing newline is
    JSONL framing, not part of the canonical byte sequence.
    """
    return dumps_jcs(payload) + b"\n"


def _canonical_bytes_of_entry(entry: dict[str, Any]) -> bytes:
    """Return the canonical bytes an entry hashes into for the chain.

    The hash covers the entry *excluding* its own newline framing; the
    ``prev_ledger_hash`` field is included so a tamper of any prior
    field is detected.
    """
    return dumps_jcs(entry)


def _hash_entry(entry: dict[str, Any]) -> str:
    """Return the hex SHA-256 of the entry's canonical bytes."""
    return hashlib.sha256(_canonical_bytes_of_entry(entry)).hexdigest()


def _utc_iso() -> str:
    """Return a UTC ISO8601 timestamp with second precision.

    Kept deliberately coarse (second, not microsecond) so identical
    manifests observed inside the same second do not spuriously diverge
    on the timestamp field alone. Deduplication is by (run_id,
    manifest_digest); timestamps are informational.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerAppendResult:
    """Return value from :meth:`ManifestLedger.append`.

    ``entry_index`` is 0 for the GENESIS entry, N for the (N+1)th entry.
    ``entry_hash`` is the hex SHA-256 of the entry's canonical bytes
    (identical to what the *next* entry's ``prev_ledger_hash`` will
    reference). ``duplicate`` is True when the append short-circuited
    because the (run_id, manifest_digest) key already exists inside
    the same run scope -- the caller receives the prior index / hash
    and no new line lands on disk.
    """

    entry_index: int
    entry_hash: str
    duplicate: bool = False


@dataclass(frozen=True)
class LedgerVerifyResult:
    """Return value from :meth:`ManifestLedger.verify_chain`.

    ``valid`` is True when every entry's ``prev_ledger_hash`` matches
    the prior entry's actual canonical-byte hash (and the first entry
    references :data:`GENESIS`). ``first_break_at`` is the index of
    the first entry whose ``prev_ledger_hash`` does NOT match; None
    when the whole chain verifies. ``tail_valid_count`` is the number
    of consecutive entries from index 0 that verify; a chain that
    breaks at index N has ``tail_valid_count == N``.
    """

    valid: bool
    first_break_at: int | None
    tail_valid_count: int


@dataclass(frozen=True)
class MerkleProof:
    """A minimal proof: for entry at index ``target_index``, the ordered
    list of subsequent entry canonical-hashes needed to walk to the tail.

    Consumers verify by recomputing SHA-256 over the ``target_entry``
    canonical bytes, then confirming that each element in
    ``forward_hashes`` is (a) the canonical hash of an entry whose
    ``prev_ledger_hash`` equals the previous element (or the target's
    own hash for the first element). This gives "this manifest was
    seen at position N of a ledger whose tail hash is X" without the
    verifier needing to hold every intermediate entry body.

    ``target_entry`` is included as a convenience so a one-shot
    verifier can recompute the initial hash without a second ledger
    read.
    """

    target_index: int
    target_entry: dict[str, Any]
    target_hash: str
    forward_hashes: tuple[str, ...]
    tail_hash: str


# ---------------------------------------------------------------------------
# Ambient ledger accessor (module_06 pattern)
# ---------------------------------------------------------------------------


# The ambient ledger mirrors the ambient run_id: a ContextVar the loop
# controller binds at ``run()`` entry and every emit-time subsystem
# (specifically :meth:`Rootknot.attest_environment`) consults when the
# caller does not pass an explicit ledger. Bare ``None`` when no loop
# is active.
_CURRENT_LEDGER: ContextVar["ManifestLedger | None"] = ContextVar(
    "ract_current_manifest_ledger", default=None
)


def get_current_ledger() -> "ManifestLedger | None":
    """Return the ambient :class:`ManifestLedger`, or ``None`` if unbound.

    :meth:`Rootknot.attest_environment` calls this after signing so an
    RK-3 attestation lands an observation without the caller having to
    thread the ledger explicitly. Unit tests that construct a knot in
    isolation see ``None`` and skip the ledger append cleanly.
    """
    return _CURRENT_LEDGER.get()


@contextmanager
def bind_ledger(ledger: "ManifestLedger") -> Iterator["ManifestLedger"]:
    """Context manager: bind ``ledger`` as the ambient for the block.

    Restores the previous ambient (typically ``None``) on exit via the
    ContextVar reset token, so nested test fixtures cannot leak a
    ledger across runs.
    """
    if not isinstance(ledger, ManifestLedger):
        raise TypeError(
            f"bind_ledger requires a ManifestLedger; got {type(ledger).__name__}"
        )
    token = _CURRENT_LEDGER.set(ledger)
    try:
        yield ledger
    finally:
        _CURRENT_LEDGER.reset(token)


# ---------------------------------------------------------------------------
# ManifestLedger -- the append-only store
# ---------------------------------------------------------------------------


class ManifestLedger:
    """Append-only JSONL ledger + content-addressable snapshot store.

    Directory layout inside ``root`` (typically ``.ract/``):

    - ``manifest_ledger.jsonl`` -- append-only JSONL of entries.
    - ``manifest_snapshots/{digest_hex}.json`` -- canonical manifest
      bytes, one file per unique digest. Written idempotently.

    The store never mutates prior entries. Rotation is out of scope
    for module_07 (flagged v0.6 gap: manifest_ledger.jsonl rotation
    with roll-forward Merkle tie).
    """

    LEDGER_NAME = "manifest_ledger.jsonl"
    SNAPSHOT_DIR_NAME = "manifest_snapshots"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self._root / self.LEDGER_NAME
        self._snapshot_dir = self._root / self.SNAPSHOT_DIR_NAME
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        # In-process serialisation. See ract.core.assumptions_wal for
        # the identical rationale: the OS file lock covers cross-process
        # safety; this threading lock covers thread-vs-thread contention
        # inside one Python process (mandatory Windows locking would
        # otherwise trip ``LedgerLockContended`` under GIL-unfair
        # scheduling before the first thread had a chance to release).
        self._thread_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Paths (test hooks)
    # ------------------------------------------------------------------

    @property
    def ledger_path(self) -> Path:
        """Absolute path to the append-only JSONL ledger file."""
        return self._ledger_path

    @property
    def snapshot_dir(self) -> Path:
        """Absolute path to the content-addressable snapshot directory."""
        return self._snapshot_dir

    def snapshot_path_for(self, digest_hex: str) -> Path:
        """Return the CAS path for ``digest_hex`` (may or may not exist)."""
        return self._snapshot_dir / f"{digest_hex}.json"

    # ------------------------------------------------------------------
    # Snapshot store
    # ------------------------------------------------------------------

    def store_snapshot(self, manifest_bytes: bytes) -> str:
        """Write ``manifest_bytes`` content-addressably and return the digest hex.

        Idempotent: if the same digest is stored twice, the second call
        is a no-op. ``manifest_bytes`` is expected to already be the
        canonical (JCS) serialisation of the manifest -- typically the
        output of
        :meth:`ract.security.manifest.ManifestDigest.canonical_bytes`.
        Callers passing arbitrary bytes get a valid CAS entry but the
        stored bytes will not compare byte-exact to what a re-hash of
        the manifest would produce.
        """
        digest_hex = hashlib.sha256(manifest_bytes).hexdigest()
        path = self.snapshot_path_for(digest_hex)
        if not path.exists():
            # Write atomically via tmp + os.replace so a mid-write kill
            # never leaves a partial snapshot at the CAS key.
            tmp_path = path.with_suffix(".json.tmp")
            fd = os.open(
                tmp_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY_FLAG,
                0o644,
            )
            try:
                os.write(fd, manifest_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp_path, path)
        return digest_hex

    def read_snapshot(self, digest_hex: str) -> bytes:
        """Return the canonical bytes stored under ``digest_hex``.

        Raises :class:`LedgerSnapshotMissingError` when the CAS file is
        absent -- the ledger entry may still exist, but the manifest
        body is not recoverable from this store.
        """
        path = self.snapshot_path_for(digest_hex)
        if not path.exists():
            raise LedgerSnapshotMissingError(
                f"no manifest snapshot at {path} for digest {digest_hex}"
            )
        return path.read_bytes()

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def iter_entries(self) -> Iterator[dict[str, Any]]:
        """Yield parsed entries in append order.

        Middle-line JSON errors raise :class:`LedgerCorruptError`. A
        malformed tail line is skipped with a WARN so a crash-during-
        append leaves the ledger readable up to the last good entry.
        """
        if not self._ledger_path.exists():
            return
        raw = self._ledger_path.read_bytes()
        if not raw:
            return
        text = raw.decode("utf-8", errors="strict")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                if i == len(lines) - 1:
                    _LOG.warning(
                        "truncated manifest_ledger tail at %s line %d "
                        "(skipped; append never fsynced before kill)",
                        self._ledger_path,
                        i,
                    )
                    return
                raise LedgerCorruptError(
                    f"malformed manifest_ledger line {i}: {exc}"
                ) from exc
            if not isinstance(obj, dict):
                raise LedgerCorruptError(
                    f"ledger line {i} is not a JSON object: {type(obj).__name__}"
                )
            yield obj

    def load(self) -> list[dict[str, Any]]:
        """Return every ledger entry as a list."""
        return list(self.iter_entries())

    def _read_entries_via_fd(self, fd: int) -> list[dict[str, Any]]:
        """Read + parse the ledger through an already-open, locked fd.

        On Windows ``msvcrt.locking`` is mandatory: opening a second
        handle to the same file to run :meth:`iter_entries` would trip
        ``PermissionError``. This helper reads bytes through the fd
        the caller already holds, so append + read-tail happen inside
        the same exclusive-lock scope.

        Parses with the same middle-strict / tail-tolerant semantics
        as :meth:`iter_entries`.
        """
        cur = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            chunks: list[bytes] = []
            while True:
                buf = os.read(fd, 65536)
                if not buf:
                    break
                chunks.append(buf)
        finally:
            os.lseek(fd, cur, os.SEEK_SET)
        raw = b"".join(chunks)
        if not raw:
            return []
        text = raw.decode("utf-8", errors="strict")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        out: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                if i == len(lines) - 1:
                    _LOG.warning(
                        "truncated manifest_ledger tail at %s line %d "
                        "(skipped; append never fsynced before kill)",
                        self._ledger_path,
                        i,
                    )
                    return out
                raise LedgerCorruptError(
                    f"malformed manifest_ledger line {i}: {exc}"
                ) from exc
            if not isinstance(obj, dict):
                raise LedgerCorruptError(
                    f"ledger line {i} is not a JSON object: {type(obj).__name__}"
                )
            out.append(obj)
        return out

    # ------------------------------------------------------------------
    # Append path
    # ------------------------------------------------------------------

    def append(
        self,
        *,
        manifest_digest: str,
        rootknot_signature: bytes,
        rootknot_run_id: str,
        manifest_bytes: bytes | None = None,
        tool_trace_summary: dict[str, Any] | None = None,
        first_wal_seq: int | None = None,
        last_wal_seq: int | None = None,
    ) -> LedgerAppendResult:
        """Append one observation to the ledger.

        Fields:

        - ``manifest_digest`` -- hex SHA-256 (64 chars). Matches the
          ``manifest_digest`` field on the observing Rootknot.
        - ``rootknot_signature`` -- the RK-3 ``environment_signature``
          bytes; base64-encoded for the JSONL row.
        - ``rootknot_run_id`` -- the 32-hex ``run_id`` (module_06
          propagation invariant).
        - ``manifest_bytes`` -- optional canonical manifest bytes; when
          present, the ledger stores them content-addressably and the
          ledger entry references ``manifest_snapshot_ref`` =
          ``"manifest_snapshots/{digest_hex}.json"``. When absent, the
          entry omits the ref -- the caller has already stored the
          snapshot elsewhere or is deliberately deferring.
        - ``tool_trace_summary`` -- optional pre-summarised trace; when
          absent, an empty summary is written (``tool_ids_invoked: []``,
          ``invocation_count: 0``). Callers with a live event log
          typically pass the result of
          :func:`summarise_tool_trace_from_events`.
        - ``first_wal_seq`` / ``last_wal_seq`` -- optional integers
          recording the RootknotWAL line count observed at append
          time. Kept optional so a test that constructs a ledger in
          isolation (without a WAL) still appends cleanly.

        Idempotence: within the same ``rootknot_run_id`` scope, the
        first append of a given ``manifest_digest`` writes; subsequent
        appends of the same pair short-circuit and return the prior
        index. Different runs observing the same manifest DO get
        distinct entries -- run-scoping preserves the "this run saw
        this manifest" attestation while deduplicating within a run.
        """
        _validate_digest_hex(manifest_digest, "manifest_digest")
        if not isinstance(rootknot_signature, (bytes, bytearray)):
            raise TypeError("rootknot_signature must be bytes")
        if not isinstance(rootknot_run_id, str) or not rootknot_run_id:
            raise ValueError("rootknot_run_id must be a non-empty string")

        # Optionally persist the manifest bytes to CAS first. This
        # happens outside the ledger lock -- CAS writes are idempotent
        # and content-addressable, so concurrent writers cannot corrupt
        # each other.
        snapshot_ref: str | None = None
        if manifest_bytes is not None:
            stored_digest = self.store_snapshot(manifest_bytes)
            if stored_digest != manifest_digest:
                raise ValueError(
                    "manifest_bytes hashes to a different digest than "
                    f"manifest_digest: bytes->{stored_digest} vs "
                    f"claimed->{manifest_digest}"
                )
            snapshot_ref = f"{self.SNAPSHOT_DIR_NAME}/{manifest_digest}.json"

        # Idempotence + prev_ledger_hash computation under a single
        # acquisition of the exclusive lock. Both operations need to
        # observe the *current* tail of the file, so a check-then-write
        # split by another writer's append would produce a stale hash.
        # Open ``RDWR`` (not ``WRONLY``) so we can slurp the current
        # contents through the same locked fd -- Windows mandatory
        # locking would refuse a second read handle otherwise.
        with self._thread_lock:
            fd = os.open(
                self._ledger_path,
                _LEDGER_OPEN_FLAGS_RDWR,
                0o644,
            )
            try:
                _lock_exclusive(fd)
                try:
                    # Re-scan tail from disk under the lock (do not
                    # trust any in-memory cache -- another process may
                    # have appended between our reads).
                    entries = self._read_entries_via_fd(fd)
                    for idx, existing in enumerate(entries):
                        if (
                            existing.get("rootknot_run_id") == rootknot_run_id
                            and existing.get("manifest_digest") == manifest_digest
                        ):
                            # Dedup hit. Return the prior index + hash
                            # so the caller can proceed as if the
                            # append had succeeded.
                            return LedgerAppendResult(
                                entry_index=idx,
                                entry_hash=_hash_entry(existing),
                                duplicate=True,
                            )

                    prev_hash: str
                    if not entries:
                        prev_hash = GENESIS
                    else:
                        prev_hash = _hash_entry(entries[-1])

                    entry = _build_entry(
                        timestamp=_utc_iso(),
                        manifest_digest=manifest_digest,
                        manifest_snapshot_ref=snapshot_ref,
                        rootknot_signature=rootknot_signature,
                        rootknot_run_id=rootknot_run_id,
                        tool_trace_summary=tool_trace_summary or {
                            "tool_ids_invoked": [],
                            "invocation_count": 0,
                            "first_invoke_at": None,
                            "last_invoke_at": None,
                        },
                        first_wal_seq=first_wal_seq,
                        last_wal_seq=last_wal_seq,
                        prev_ledger_hash=prev_hash,
                    )
                    line = _canonical_line(entry)
                    os.write(fd, line)
                    os.fsync(fd)
                    entry_hash = _hash_entry(entry)
                    entry_index = len(entries)
                finally:
                    _unlock(fd)
            finally:
                os.close(fd)

        # Emit the trace event OUTSIDE the lock. Emit failure is not
        # allowed to corrupt the ledger, and holding the lock across
        # an event-writer call widens the critical section unnecessarily.
        try:
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "manifest.ledger.appended",
                {
                    "entry_index": entry_index,
                    "manifest_digest": manifest_digest,
                    "prev_ledger_hash": (
                        prev_hash if prev_hash != GENESIS else "GENESIS"
                    ),
                    "tool_ids_invoked_count": len(
                        (tool_trace_summary or {}).get("tool_ids_invoked", [])
                    ),
                },
            )
        except Exception:  # noqa: BLE001 -- trace failure never invalidates the append
            _LOG.debug("manifest.ledger.appended emit failed", exc_info=True)

        return LedgerAppendResult(
            entry_index=entry_index,
            entry_hash=entry_hash,
            duplicate=False,
        )

    # ------------------------------------------------------------------
    # Verify path
    # ------------------------------------------------------------------

    def verify_chain(self) -> LedgerVerifyResult:
        """Walk the ledger and verify every ``prev_ledger_hash`` link.

        Return :class:`LedgerVerifyResult` with:

        - ``valid=True`` when the whole chain links cleanly.
        - ``first_break_at`` set to the smallest index N whose
          ``prev_ledger_hash`` does NOT match the actual hash of the
          entry at N-1 (or, for N=0, does not equal :data:`GENESIS`).
        - ``tail_valid_count`` = N when the break is at index N; N
          equals the total count when the chain is fully valid.

        A truncated tail (dropped last entry after export/tampering)
        surfaces as a chain that verifies cleanly but with fewer
        entries -- the caller compares ``tail_valid_count`` to the
        expected length to detect that class of tamper.
        """
        entries = self.load()
        if not entries:
            return LedgerVerifyResult(
                valid=True, first_break_at=None, tail_valid_count=0
            )
        for i, entry in enumerate(entries):
            expected_prev: str
            if i == 0:
                expected_prev = GENESIS
            else:
                expected_prev = _hash_entry(entries[i - 1])
            claimed_prev = entry.get("prev_ledger_hash")
            if claimed_prev != expected_prev:
                return LedgerVerifyResult(
                    valid=False,
                    first_break_at=i,
                    tail_valid_count=i,
                )
        return LedgerVerifyResult(
            valid=True,
            first_break_at=None,
            tail_valid_count=len(entries),
        )

    # ------------------------------------------------------------------
    # Merkle proof
    # ------------------------------------------------------------------

    def proof_of(self, entry_index: int) -> MerkleProof:
        """Return a Merkle-style proof that entry ``entry_index`` is on the chain.

        The proof is the list of canonical-byte hashes for every entry
        from ``entry_index`` to the tail. An offline verifier:

        1. Recomputes ``target_hash`` from ``target_entry``.
        2. For each hash H in ``forward_hashes``, loads the JSONL entry
           whose canonical hash equals H (or, in a compact deployment,
           receives it out of band) and checks that its
           ``prev_ledger_hash`` equals the previous H (or
           ``target_hash`` for the first element).
        3. Confirms ``forward_hashes[-1] == tail_hash`` (or that
           ``forward_hashes`` is empty AND ``target_hash == tail_hash``
           when the target IS the tail).

        Raises ``IndexError`` when ``entry_index`` is out of range.
        """
        entries = self.load()
        if entry_index < 0 or entry_index >= len(entries):
            raise IndexError(
                f"entry_index {entry_index} out of range (ledger has "
                f"{len(entries)} entries)"
            )
        target = entries[entry_index]
        target_hash = _hash_entry(target)
        forward = tuple(_hash_entry(entries[j]) for j in range(entry_index + 1, len(entries)))
        tail_hash = forward[-1] if forward else target_hash
        return MerkleProof(
            target_index=entry_index,
            target_entry=target,
            target_hash=target_hash,
            forward_hashes=forward,
            tail_hash=tail_hash,
        )

    @staticmethod
    def verify_proof(
        proof: MerkleProof,
        loader: Callable[[str], dict[str, Any]] | None = None,
    ) -> bool:
        """Return True when ``proof`` is internally consistent.

        Without a ``loader`` the check is limited to the invariants
        computable from the proof alone:

        - The target entry's canonical hash matches ``target_hash``.
        - When ``forward_hashes`` is empty, ``target_hash == tail_hash``.
        - When ``forward_hashes`` is non-empty, its last element equals
          ``tail_hash``.

        Passing a ``loader(hash_hex) -> dict`` lets the verifier walk
        the full chain: for each hash in ``forward_hashes``, load the
        entry with that canonical hash and confirm its ``prev_ledger_hash``
        equals the previous element (or ``target_hash`` for the first
        element). Loader-based verification is stricter and closer to
        the real "proof of inclusion" property.
        """
        if _hash_entry(proof.target_entry) != proof.target_hash:
            return False
        if not proof.forward_hashes:
            return proof.target_hash == proof.tail_hash
        if proof.forward_hashes[-1] != proof.tail_hash:
            return False
        if loader is None:
            return True
        prev_hash = proof.target_hash
        for h in proof.forward_hashes:
            try:
                next_entry = loader(h)
            except Exception:
                return False
            if not isinstance(next_entry, dict):
                return False
            if next_entry.get("prev_ledger_hash") != prev_hash:
                return False
            if _hash_entry(next_entry) != h:
                return False
            prev_hash = h
        return True


# ---------------------------------------------------------------------------
# Entry construction (module-private)
# ---------------------------------------------------------------------------


def _build_entry(
    *,
    timestamp: str,
    manifest_digest: str,
    manifest_snapshot_ref: str | None,
    rootknot_signature: bytes,
    rootknot_run_id: str,
    tool_trace_summary: dict[str, Any],
    first_wal_seq: int | None,
    last_wal_seq: int | None,
    prev_ledger_hash: str,
) -> dict[str, Any]:
    """Build the canonical entry dict.

    The entry field order does not matter -- JCS sorts keys at serialise
    time -- but keeping the assembly explicit here documents the schema.
    """
    entry: dict[str, Any] = {
        "timestamp": timestamp,
        "manifest_digest": manifest_digest,
        "rootknot_signature": base64.b64encode(bytes(rootknot_signature)).decode("ascii"),
        "rootknot_run_id": rootknot_run_id,
        "tool_trace_summary": _normalise_tool_trace(tool_trace_summary),
        "prev_ledger_hash": prev_ledger_hash,
    }
    if manifest_snapshot_ref is not None:
        entry["manifest_snapshot_ref"] = manifest_snapshot_ref
    if first_wal_seq is not None or last_wal_seq is not None:
        entry["wal_cross_link"] = {
            "first_wal_seq": first_wal_seq if first_wal_seq is not None else 0,
            "last_wal_seq": last_wal_seq if last_wal_seq is not None else 0,
        }
    return entry


def _normalise_tool_trace(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``summary`` with a stable schema and JSON types.

    Kept small: the ledger records SUMMARY (count + first/last), not the
    full trace -- the full trace lives in the event log. This keeps
    ledger lines bounded even for a run that invokes thousands of
    tools.
    """
    tool_ids = tuple(str(t) for t in summary.get("tool_ids_invoked", ()))
    count = int(summary.get("invocation_count", 0))
    first = summary.get("first_invoke_at")
    last = summary.get("last_invoke_at")
    return {
        "tool_ids_invoked": sorted(set(tool_ids)),
        "invocation_count": count,
        "first_invoke_at": first if first is not None else None,
        "last_invoke_at": last if last is not None else None,
    }


def _validate_digest_hex(value: str, field_name: str) -> None:
    """Raise ValueError if ``value`` is not a 64-char lowercase hex string."""
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(
            f"{field_name} must be a 64-char SHA-256 hex string; got "
            f"{type(value).__name__}({len(value) if isinstance(value, str) else '-'})"
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not valid hex: {exc}") from exc


# ---------------------------------------------------------------------------
# Public helper: summarise a tool trace from event-log entries
# ---------------------------------------------------------------------------


def summarise_tool_trace_from_events(
    events: Sequence[dict[str, Any]] | Sequence[Any],
) -> dict[str, Any]:
    """Return a bounded tool_trace_summary from a sequence of events.

    Accepts either dict-shaped events (``{'kind': ..., 'payload': ...,
    'timestamp_ns': ...}``) or objects with attributes of the same
    names (``ract.trace.events.Event`` values satisfy this). Only
    events with ``kind == "tool.called"`` are counted. ``tool_id`` is
    read from the payload's ``tool_id`` key (falling back to ``name``
    when absent).
    """
    tool_ids: list[str] = []
    first_ns: int | None = None
    last_ns: int | None = None
    count = 0
    for ev in events:
        kind = _ev_field(ev, "kind")
        if kind != "tool.called":
            continue
        payload = _ev_field(ev, "payload") or {}
        tid = str(payload.get("tool_id") or payload.get("name") or "unknown")
        tool_ids.append(tid)
        ts = _ev_field(ev, "timestamp_ns")
        if isinstance(ts, int):
            if first_ns is None or ts < first_ns:
                first_ns = ts
            if last_ns is None or ts > last_ns:
                last_ns = ts
        count += 1
    return {
        "tool_ids_invoked": tool_ids,
        "invocation_count": count,
        "first_invoke_at": _ns_to_iso(first_ns),
        "last_invoke_at": _ns_to_iso(last_ns),
    }


def _ev_field(ev: Any, name: str) -> Any:
    if isinstance(ev, dict):
        return ev.get(name)
    return getattr(ev, name, None)


def _ns_to_iso(ns: int | None) -> str | None:
    if ns is None:
        return None
    seconds = ns / 1_000_000_000
    return (
        datetime.fromtimestamp(seconds, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# WAL cross-link helper
# ---------------------------------------------------------------------------


def count_wal_entries(wal: Any) -> int:
    """Return the total number of lines in ``wal``'s underlying files.

    Accepts a :class:`ract.core.assumptions_wal.AssumptionWal` (or any
    object exposing :meth:`load_all` with the same return shape) and
    returns ``len(snapshot_entries) + len(wal_entries)``. Used as the
    RootknotWAL "sequence" for the ledger's ``wal_cross_link`` field --
    the WAL itself does not carry explicit seq numbers, so line-count-
    at-append-time is the closest stable identifier.
    """
    if wal is None:
        return 0
    try:
        snapshot_entries, wal_entries = wal.load_all()
    except AttributeError:
        return 0
    return len(snapshot_entries) + len(wal_entries)


# ---------------------------------------------------------------------------
# Wire helper -- called by Rootknot.attest_environment
# ---------------------------------------------------------------------------


def record_environment_attestation(
    knot: Any,
    *,
    ledger: "ManifestLedger | None" = None,
    manifest_bytes: bytes | None = None,
    tool_trace_summary: dict[str, Any] | None = None,
    wal: Any | None = None,
    first_wal_seq: int | None = None,
    last_wal_seq: int | None = None,
) -> LedgerAppendResult | None:
    """Record ``knot``'s RK-3 attestation in ``ledger`` (or the ambient one).

    Returns the :class:`LedgerAppendResult` when an entry was written
    or deduplicated; returns ``None`` when no ledger was available
    (test fixtures that construct a knot in isolation). Callers do not
    need to handle the None case unless they explicitly want to detect
    "ambient was unbound".

    The helper skips the append cleanly when:

    - ``knot`` lacks a ``manifest_digest`` (a v1 Rootknot or one built
      without a manifest);
    - ``knot`` lacks an ``environment_signature`` (RK-3 not yet
      attested);
    - ``knot`` lacks a ``run_id`` (v3-or-earlier Rootknot);
    - no ledger is bound.

    None of these are error states -- they represent legitimate paths
    (v3 knots, unit tests, etc). Emitting a warning in any of them
    would spam the audit log.
    """
    if ledger is None:
        ledger = get_current_ledger()
    if ledger is None:
        return None
    manifest_digest = getattr(knot, "manifest_digest", None)
    if manifest_digest is None or all(b == 0 for b in bytes(manifest_digest)):
        return None
    environment_signature = getattr(knot, "environment_signature", None)
    if not environment_signature:
        return None
    run_id = getattr(knot, "run_id", None)
    if not run_id:
        return None
    if wal is not None and first_wal_seq is None and last_wal_seq is None:
        seq = count_wal_entries(wal)
        first_wal_seq = seq
        last_wal_seq = seq
    return ledger.append(
        manifest_digest=bytes(manifest_digest).hex(),
        rootknot_signature=bytes(environment_signature),
        rootknot_run_id=str(run_id),
        manifest_bytes=manifest_bytes,
        tool_trace_summary=tool_trace_summary,
        first_wal_seq=first_wal_seq,
        last_wal_seq=last_wal_seq,
    )


# RACT 0.5.1
