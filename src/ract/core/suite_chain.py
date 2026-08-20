"""Append-only suite chain for v0.5.1 module_04.

The suite chain records every ``AcceptanceSuite`` a run has operated
under. The initial suite from ``IntentCompiler.compile`` is entry 0;
each operator-signed ``ract intent recompile`` appends a new entry.
The loop controller compares the current intent against the LATEST
entry's ``prompt_digest``, so a legitimate operator refine-and-recompile
flow lets the loop continue while an attacker's silent intent mutation
trips T8 (no matching chain entry exists).

Persistence: ``<run_dir>/suite_chain.jsonl``. One RFC-8785 JCS line
per entry. Each line is a JSON object with:

- ``timestamp_ns`` -- ``time.time_ns()`` at append time.
- ``prompt_digest`` -- hex SHA-256 of the intent text (32 bytes,
  matches ``AcceptanceSuite.prompt_digest`` bytes).
- ``suite_digest`` -- hex SHA-256 of the suite's canonical JSON
  (matches ``AcceptanceSuite.digest()``).
- ``rootknot_signature`` -- hex generator signature of the v4
  Rootknot recording the recompile action. Only present for
  operator-signed recompiles; ``None`` for the initial compile.
- ``run_id`` -- the run identifier this chain belongs to.
- ``origin`` -- ``"initial"`` for the first entry,
  ``"operator_recompile"`` for every subsequent entry.

The chain follows the same file-lock / thread-lock / binary-mode
discipline as :mod:`ract.core.assumptions_wal` and
:mod:`ract.core.workspace_digest` so a reviewer sees ONE persistence
idiom across module_01/02/04.

Read semantics:

- ``entries()`` returns the parsed entries in append order.
- ``latest()`` returns the most recent entry (or ``None`` when the
  chain does not exist yet).
- ``latest_prompt_digest()`` returns the raw 32-byte prompt digest
  of the last entry (bytes for direct comparison against
  ``suite.prompt_digest``); returns ``None`` when the chain is empty.

Reference:
- ``_BUILD/ract_v0.5.1_external_review_response/module_04.md``.
- ``docs/ADRs/ADR-0040-t8-prompt-drift-termination-cause.md``.
- ``src/ract/core/assumptions_wal.py`` (file-lock template).
- ``src/ract/core/workspace_digest.py`` (chain-ledger template).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("ract.core.suite_chain")

from ract.canonical import dumps_jcs
from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SuiteChainCorruptError(RuntimeError):
    """Raised when a middle line of ``suite_chain.jsonl`` is malformed.

    Mirrors :class:`ract.core.workspace_digest.WorkspaceChainCorruptError`
    -- a truncated *tail* line is tolerated with a WARN; a malformed
    *middle* line is a hard failure (non-append corruption).
    """


class SuiteChainLockContended(RuntimeError):
    """Raised when the suite-chain lock cannot be acquired after retries."""


# ---------------------------------------------------------------------------
# Cross-platform file locking (mirror of workspace_digest.py)
# ---------------------------------------------------------------------------


_LOCK_RETRIES = 3
_LOCK_BACKOFF_S = 0.01

_BINARY_FLAG = getattr(os, "O_BINARY", 0)
_CHAIN_OPEN_FLAGS_APPEND = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _BINARY_FLAG


if sys.platform == "win32":
    import msvcrt  # type: ignore[import-not-found]

    def _lock_exclusive(fd: int) -> None:
        cur = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            for attempt in range(_LOCK_RETRIES):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    if attempt == _LOCK_RETRIES - 1:
                        raise SuiteChainLockContended(
                            "suite_chain.jsonl is locked by another RACT "
                            f"process; gave up after {_LOCK_RETRIES} attempts"
                        )
                    time.sleep(_LOCK_BACKOFF_S)
        finally:
            os.lseek(fd, cur, os.SEEK_SET)

    def _unlock(fd: int) -> None:
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
        for attempt in range(_LOCK_RETRIES):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if attempt == _LOCK_RETRIES - 1:
                    raise SuiteChainLockContended(
                        "suite_chain.jsonl is locked by another RACT "
                        f"process; gave up after {_LOCK_RETRIES} attempts"
                    )
                time.sleep(_LOCK_BACKOFF_S)

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public data + API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuiteChainEntry:
    """One parsed suite-chain entry."""

    timestamp_ns: int
    prompt_digest: bytes  # 32-byte SHA-256
    suite_digest: str  # hex
    rootknot_signature: str | None  # hex, None for initial
    run_id: str
    origin: str  # "initial" | "operator_recompile"


class SuiteChain:
    """Append-only ledger of suites for a single run.

    Persists at ``<run_dir>/suite_chain.jsonl``.
    """

    CHAIN_NAME = "suite_chain.jsonl"

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = Path(run_dir)
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._chain_path = self._run_dir / self.CHAIN_NAME
        self._thread_lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._chain_path

    def append(
        self,
        *,
        prompt_digest: bytes,
        suite_digest: str,
        run_id: str,
        origin: str,
        rootknot_signature: bytes | None = None,
        timestamp_ns: int | None = None,
    ) -> SuiteChainEntry:
        """Record a new suite version.

        Atomic under the cross-platform lock. Returns the parsed
        :class:`SuiteChainEntry` that was written so callers can log or
        return it without re-reading the file.
        """
        if len(prompt_digest) != 32:
            raise ValueError(
                "prompt_digest must be 32 bytes (SHA-256); "
                f"got {len(prompt_digest)}"
            )
        if origin not in {"initial", "operator_recompile"}:
            raise ValueError(
                f"origin must be 'initial' or 'operator_recompile'; got {origin!r}"
            )
        ts = time.time_ns() if timestamp_ns is None else int(timestamp_ns)
        sig_hex = rootknot_signature.hex() if rootknot_signature else None
        payload: dict[str, Any] = {
            "origin": origin,
            "prompt_digest": prompt_digest.hex(),
            "rootknot_signature": sig_hex,
            "run_id": run_id,
            "suite_digest": suite_digest,
            "timestamp_ns": ts,
        }
        line = dumps_jcs(payload) + b"\n"
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
        return SuiteChainEntry(
            timestamp_ns=ts,
            prompt_digest=prompt_digest,
            suite_digest=suite_digest,
            rootknot_signature=sig_hex,
            run_id=run_id,
            origin=origin,
        )

    def entries(self) -> list[SuiteChainEntry]:
        """Return the parsed entries in append order."""
        if not self._chain_path.exists():
            return []
        self._thread_lock.acquire()
        try:
            fd = os.open(self._chain_path, os.O_RDONLY | _BINARY_FLAG)
            try:
                _lock_exclusive(fd)
                try:
                    chunks: list[bytes] = []
                    while True:
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                finally:
                    _unlock(fd)
            finally:
                os.close(fd)
        finally:
            self._thread_lock.release()
        if not raw:
            return []
        if raw.endswith(b"\n"):
            raw = raw[:-1]
        lines = raw.split(b"\n")
        parsed: list[SuiteChainEntry] = []
        for idx, line in enumerate(lines):
            try:
                payload = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                if idx == len(lines) - 1:
                    _LOG.warning(
                        "suite_chain.jsonl: truncated tail at line %d in %s; "
                        "stopping replay at last-known-good entry",
                        idx,
                        self._chain_path,
                    )
                    break
                raise SuiteChainCorruptError(
                    f"suite_chain.jsonl: malformed middle line at index {idx} in "
                    f"{self._chain_path}"
                )
            if not isinstance(payload, dict) or "prompt_digest" not in payload:
                if idx == len(lines) - 1:
                    _LOG.warning(
                        "suite_chain.jsonl: unexpected tail payload at line %d "
                        "in %s; stopping replay",
                        idx,
                        self._chain_path,
                    )
                    break
                raise SuiteChainCorruptError(
                    f"suite_chain.jsonl: malformed middle payload at index {idx} "
                    f"in {self._chain_path}"
                )
            try:
                digest_bytes = bytes.fromhex(str(payload["prompt_digest"]))
            except ValueError:
                raise SuiteChainCorruptError(
                    f"suite_chain.jsonl: prompt_digest is not hex at index {idx} in "
                    f"{self._chain_path}"
                )
            parsed.append(
                SuiteChainEntry(
                    timestamp_ns=int(payload.get("timestamp_ns", 0)),
                    prompt_digest=digest_bytes,
                    suite_digest=str(payload.get("suite_digest", "")),
                    rootknot_signature=(
                        None
                        if payload.get("rootknot_signature") is None
                        else str(payload.get("rootknot_signature"))
                    ),
                    run_id=str(payload.get("run_id", "")),
                    origin=str(payload.get("origin", "initial")),
                )
            )
        return parsed

    def latest(self) -> SuiteChainEntry | None:
        """Return the most recent entry, or ``None`` when the chain is empty."""
        rows = self.entries()
        return rows[-1] if rows else None

    def latest_prompt_digest(self) -> bytes | None:
        """Return the last entry's raw 32-byte digest, or ``None`` when empty.

        Convenience for the loop-controller T8 hook: the comparison
        target is the byte value, not the hex string.
        """
        last = self.latest()
        return None if last is None else last.prompt_digest


# RACT 0.5.1
