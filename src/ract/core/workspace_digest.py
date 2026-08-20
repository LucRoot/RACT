"""Workspace-digest primitives for v0.5.1 module_02.

DEEPSEEK_REVIEW_5 §"G2 deeper dive" identified that ``Rootknot``'s
signed canonical bytes bind the artifact + environment + gates but do
NOT bind the *workspace snapshot* that was in force at write time. Over
200 compactions this becomes load-bearing: an artifact from compaction
#117 verifies against compaction #118's workspace even after a refactor
because the signature is not tied to the snapshot. The signed payload
answers "was this authored by an authorised generator in an attested
sandbox?" — but not "against WHICH workspace state?".

This module supplies the primitives module_02 wires into the extended
canonical bytes:

- :func:`workspace_digest` — pure SHA-256 over the canonical
  serialisation of a :class:`ract.core.loop.WorkspaceSnapshot`. The
  digest becomes the ``workspace_digest`` field on v4 Rootknots so the
  generator + environment + anti-lazy signatures all attest over it.
- :class:`WorkspaceDigestChain` — append-only ledger at
  ``.ract/workspace_chain.jsonl`` recording ``(child_digest,
  parent_digest)`` edges. Verify-time helper
  :meth:`is_ancestor` walks the parent chain so a compaction can
  answer "is snapshot #117 an ancestor of snapshot #118?" without
  requiring a git substrate. Chain uses the same file-lock discipline
  as :mod:`ract.core.assumptions_wal` — cross-platform
  ``msvcrt.locking`` / ``fcntl.flock``, same one-byte range,
  three-attempts-with-backoff retry.
- :func:`run_id_hex` — helper for generating stable 16-byte hex run
  identifiers. Mirrors the shape of :func:`ract.core.types.make_plan_id`
  so callers can join Rootknots to WAL entries + trace events by
  string equality.

Design choice (Lateral chain branch B in module_02.md): pure hash for
the field IN THE SIGNED PAYLOAD (deterministic, stateless, no I/O, no
git dependency); ledger-based ancestry separate from the signed bytes
(verify-time predicate, not attest-time field). This matches DeepSeek
R5's *primary* description of workspace_digest as "SHA-256 over the
``WorkspaceSnapshot.files`` sorted + timestamp + metadata hash" — the
git-commit variant was offered only as a "simpler first cut" for teams
without an ambient hash-computation surface. RACT already has canonical
JSON + SHA-256 everywhere; pure hash is materially less complex here.

Reference:
- ``_BUILD/ract_v0.5.1_external_review/DEEPSEEK_REVIEW_5.md`` §G2.
- ``_BUILD/ract_v0.5.1_external_review_response/module_02.md``.
- ``src/ract/core/assumptions_wal.py`` (file-lock template).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

_LOG = logging.getLogger("ract.core.workspace_digest")

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract.core.types import Digest

if TYPE_CHECKING:
    from ract.core.loop import WorkspaceSnapshot


# ---------------------------------------------------------------------------
# Pure-hash workspace_digest
# ---------------------------------------------------------------------------


def _stable_metadata_hash(metadata: dict[str, Any]) -> str:
    """Return a stable hex hash of ``metadata`` values.

    ``ws.metadata`` can carry non-JSON-serialisable side-channel values
    (e.g. custom objects from evaluator subprocesses). ``default=str``
    coerces them via ``str()`` — deterministic given a stable repr,
    which is the invariant every Python callable respects.
    """
    payload = json.dumps(metadata, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def workspace_digest(ws: "WorkspaceSnapshot") -> Digest:
    """Return the SHA-256 :class:`Digest` binding a workspace snapshot.

    Hash input is a canonical JSON serialisation of:

    - ``files`` — sorted by path so map-order does not perturb the hash.
    - ``timestamp`` — float; Python's IEEE 754 repr is deterministic.
    - ``metadata_hash`` — SHA-256 of a canonical dump of the metadata
      dict (via :func:`_stable_metadata_hash`), so the workspace_digest
      itself is small (one hex string in the outer payload) but any
      metadata change still propagates to the top-level digest.

    Determinism: same ``ws`` produces the same digest across processes
    and Python versions (:leaf L1 in module_02 Depth chain). Single
    byte-flip in any file content produces a different digest (leaf L2).
    """
    files_sorted = sorted(ws.files.items(), key=lambda kv: kv[0])
    payload = {
        "files": files_sorted,
        "timestamp": ws.timestamp,
        "metadata_hash": _stable_metadata_hash(ws.metadata),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return Digest(hashlib.sha256(canonical.encode("utf-8")).digest())


# ---------------------------------------------------------------------------
# prompt_digest helper
# ---------------------------------------------------------------------------


def compute_prompt_digest(intent_text: str) -> Digest:
    """Return SHA-256 of ``intent_text``'s UTF-8 bytes.

    Byte-level sensitivity: a single character change in the intent
    produces a different digest (leaf L3). Used by
    :class:`ract.core.compile.IntentCompiler` to populate
    :attr:`ract.core.predicate.AcceptanceSuite.prompt_digest`; the
    Rootknot's ``prompt_digest`` field carries the same value so the
    signed canonical bytes bind the run to its originating prompt.
    """
    return Digest(hashlib.sha256(intent_text.encode("utf-8")).digest())


# ---------------------------------------------------------------------------
# run_id helper
# ---------------------------------------------------------------------------


def run_id_hex() -> str:
    """Return a fresh 32-hex-char run identifier.

    Mirrors the shape of :func:`ract.core.types.make_plan_id` but as a
    plain string so it can flow through JSON payloads (WAL entries,
    trace events, ``Rootknot.canonical_bytes`` output) without hex
    round-tripping at every hop.
    """
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# WorkspaceDigestChain — append-only ancestry ledger
# ---------------------------------------------------------------------------


class WorkspaceChainCorruptError(RuntimeError):
    """Raised when a middle line in the chain ledger is malformed.

    Mirrors :class:`ract.core.assumptions_wal.WalCorruptError` — a
    truncated *tail* line is tolerated with a WARN; a malformed
    *middle* line is a hard failure (non-append corruption).
    """


class WorkspaceChainLockContended(RuntimeError):
    """Raised when the chain-ledger lock cannot be acquired after retries.

    Mirrors :class:`ract.core.assumptions_wal.WalLockContended` — a
    concurrent RACT process on the same tree holds the ledger lock
    and did not release within the retry window.
    """


_LOCK_RETRIES = 3
_LOCK_BACKOFF_S = 0.01

# ``O_BINARY`` on Windows; no-op flag on POSIX. Same lesson as
# module_01: byte-exact JSONL streams must open in binary mode on
# Windows to prevent CRLF translation.
_BINARY_FLAG = getattr(os, "O_BINARY", 0)
_CHAIN_OPEN_FLAGS_APPEND = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _BINARY_FLAG


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
                        raise WorkspaceChainLockContended(
                            "workspace_chain.jsonl is locked by another RACT "
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
                    raise WorkspaceChainLockContended(
                        "workspace_chain.jsonl is locked by another RACT "
                        f"process; gave up after {_LOCK_RETRIES} attempts"
                    )
                time.sleep(_LOCK_BACKOFF_S)

    def _unlock(fd: int) -> None:
        """Release the advisory lock previously held on ``fd``."""
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


def _canonical_edge_line(payload: dict[str, Any]) -> bytes:
    """Return one canonical JSONL line for a chain edge."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


@dataclass(frozen=True)
class ChainEdge:
    """One parsed chain-ledger edge.

    ``child`` is the child snapshot's hex digest; ``parent`` is the
    parent's hex digest, or ``None`` for a root snapshot.
    """

    child: str
    parent: str | None


class WorkspaceDigestChain:
    """Append-only parent chain of workspace digests.

    Persists at ``chain_dir / "workspace_chain.jsonl"``. Every append is
    a single canonical JSONL line, one edge per line. Reads replay the
    full file; concurrent writers serialise on the cross-platform file
    lock. Same discipline as :class:`ract.core.assumptions_wal.AssumptionWal`
    — this module intentionally follows the module_01 template so a
    reviewer sees one persistence idiom, not two.

    A snapshot digest may appear at most once as a *child* (its parent
    is fixed at first recording). A digest may appear many times as a
    *parent* (the chain is a tree, not a linear list — a workspace
    can branch).
    """

    CHAIN_NAME = "workspace_chain.jsonl"

    def __init__(self, chain_dir: Path) -> None:
        self._chain_dir = Path(chain_dir)
        self._chain_dir.mkdir(parents=True, exist_ok=True)
        self._chain_path = self._chain_dir / self.CHAIN_NAME
        # An in-process threading lock is layered on top of the OS
        # file lock (module_01 POST-B lesson: GIL-unfair scheduling
        # defeats short-retry file locks under intra-process contention).
        import threading

        self._thread_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def append(self, child: Digest, parent: Digest | None) -> None:
        """Record an edge ``child -> parent``.

        Parent is ``None`` for a root snapshot. The append is atomic
        under the cross-platform lock: no concurrent writer can inject
        a line between the seek + write.
        """
        child_hex = child.hex() if isinstance(child, (bytes, bytearray)) else str(child)
        parent_hex = (
            parent.hex()
            if parent is not None and isinstance(parent, (bytes, bytearray))
            else (None if parent is None else str(parent))
        )
        payload: dict[str, Any] = {"child": child_hex, "parent": parent_hex}
        line = _canonical_edge_line(payload)
        self._thread_lock.acquire()
        try:
            fd = os.open(self._chain_path, _CHAIN_OPEN_FLAGS_APPEND, 0o644)
            try:
                _lock_exclusive(fd)
                try:
                    os.write(fd, line)
                    os.fsync(fd)
                finally:
                    _unlock(fd)
            finally:
                os.close(fd)
        finally:
            self._thread_lock.release()

    def edges(self) -> list[ChainEdge]:
        """Return the ledger's edges in append order.

        Tolerates a truncated *tail* line (last line only) with a WARN.
        A malformed *middle* line raises
        :class:`WorkspaceChainCorruptError` — non-append corruption is
        not tolerable.
        """
        if not self._chain_path.exists():
            return []
        with open(self._chain_path, "rb") as fh:
            raw = fh.read()
        if not raw:
            return []
        # Strip a trailing single ``\n`` so we do not manufacture an
        # empty trailing line to skip.
        if raw.endswith(b"\n"):
            raw = raw[:-1]
        lines = raw.split(b"\n")
        edges: list[ChainEdge] = []
        for idx, line in enumerate(lines):
            try:
                payload = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Tail-line tolerance: if this is the last line, warn
                # and stop; if it's a middle line, raise.
                if idx == len(lines) - 1:
                    _LOG.warning(
                        "workspace_chain.jsonl: truncated tail at line %d in %s; "
                        "stopping replay at last-known-good edge",
                        idx,
                        self._chain_path,
                    )
                    break
                raise WorkspaceChainCorruptError(
                    f"workspace_chain.jsonl: malformed middle line at index {idx} in "
                    f"{self._chain_path}"
                )
            if not isinstance(payload, dict) or "child" not in payload:
                if idx == len(lines) - 1:
                    _LOG.warning(
                        "workspace_chain.jsonl: unexpected tail payload at line %d "
                        "in %s; stopping replay",
                        idx,
                        self._chain_path,
                    )
                    break
                raise WorkspaceChainCorruptError(
                    f"workspace_chain.jsonl: malformed middle payload at index {idx} "
                    f"in {self._chain_path}"
                )
            edges.append(
                ChainEdge(child=str(payload["child"]), parent=payload.get("parent"))
            )
        return edges

    def parent_of(self, child: Digest | str) -> str | None:
        """Return the parent hex digest of ``child``, or ``None`` if root/unknown."""
        child_hex = (
            child.hex() if isinstance(child, (bytes, bytearray)) else str(child)
        )
        for edge in self.edges():
            if edge.child == child_hex:
                return edge.parent
        return None

    def is_ancestor(
        self, ancestor: Digest | str, descendant: Digest | str
    ) -> bool:
        """Return ``True`` iff ``ancestor`` lies on ``descendant``'s parent chain.

        Walks the parent chain from ``descendant`` upward. A descendant
        is NOT considered its own ancestor (``is_ancestor(x, x)`` is
        ``False``) — matches the ``git merge-base --is-ancestor``
        convention where a commit is its own ancestor is a
        configuration-dependent edge; the more useful predicate here is
        strict parenthood. Callers wanting the reflexive variant should
        add the equality check at the call site.

        A cycle in the ledger (malformed writer) is detected via a
        visited set and stops the walk; the return value is ``False``
        for the cycle-containing chain (no ancestry proof possible).
        """
        ancestor_hex = (
            ancestor.hex()
            if isinstance(ancestor, (bytes, bytearray))
            else str(ancestor)
        )
        descendant_hex = (
            descendant.hex()
            if isinstance(descendant, (bytes, bytearray))
            else str(descendant)
        )
        if ancestor_hex == descendant_hex:
            return False
        # Build a child -> parent map once for O(depth) traversal.
        parent_map: dict[str, str | None] = {}
        for edge in self.edges():
            # First-write-wins: a child appearing twice keeps the earlier
            # parent binding.
            parent_map.setdefault(edge.child, edge.parent)
        visited: set[str] = set()
        cursor: str | None = descendant_hex
        while cursor is not None:
            if cursor in visited:
                _LOG.warning(
                    "workspace_chain.jsonl: cycle detected at %s in %s; "
                    "aborting ancestor walk",
                    cursor,
                    self._chain_path,
                )
                return False
            visited.add(cursor)
            parent = parent_map.get(cursor)
            if parent is None:
                return False
            if parent == ancestor_hex:
                return True
            cursor = parent
        return False


# RACT 0.5.1
