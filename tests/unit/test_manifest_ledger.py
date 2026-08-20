"""Regression tests for the Historical Manifest Ledger (v0.5.1 module_07).

Pins the load-bearing invariants:

- append + fsync + iter round-trips byte-exact;
- ``prev_ledger_hash`` chain verifies for a clean append sequence;
- GENESIS sentinel drives the first entry's ``prev_ledger_hash``;
- content-addressable snapshot dedup writes the file once;
- ``verify_chain`` detects a tampered middle entry;
- ``verify_chain`` reports a truncated tail as fewer valid entries
  (chain itself still verifies -- the count exposes the tamper);
- Merkle proof round-trips against ``verify_proof``;
- append is idempotent within one (run_id, manifest_digest) pair;
- cross-platform lock refuses a concurrent held lock;
- POSIX-only lock path is skipped on Windows and vice versa.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from ract.canonical import dumps_jcs
from ract.security.manifest_ledger import (
    GENESIS,
    LedgerAppendResult,
    LedgerCorruptError,
    LedgerLockContended,
    LedgerSnapshotMissingError,
    ManifestLedger,
    MerkleProof,
    _canonical_line,
    _hash_entry,
    _lock_exclusive,
    _unlock,
    bind_ledger,
    count_wal_entries,
    get_current_ledger,
    record_environment_attestation,
    summarise_tool_trace_from_events,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_ledger(tmp_path: Path) -> ManifestLedger:
    return ManifestLedger(tmp_path / ".ract")


def _mk_digest(seed: int) -> str:
    """Return a deterministic 32-byte hex from ``seed`` (test fixture)."""
    import hashlib

    return hashlib.sha256(f"digest-{seed}".encode("utf-8")).hexdigest()


def _mk_signature(seed: int) -> bytes:
    """Return a deterministic 64-byte pseudo-signature (test fixture)."""
    import hashlib

    return hashlib.sha512(f"sig-{seed}".encode("utf-8")).digest()


def _mk_run_id(seed: int) -> str:
    """Return a deterministic 32-hex run_id (test fixture)."""
    import hashlib

    return hashlib.sha256(f"run-{seed}".encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Canonical / hash helpers
# ---------------------------------------------------------------------------


def test_canonical_line_is_stable_sorted() -> None:
    """The canonical JSONL line is byte-stable across key orderings."""
    a = _canonical_line({"b": 1, "a": 2, "manifest_digest": "x"})
    b = _canonical_line({"manifest_digest": "x", "a": 2, "b": 1})
    assert a == b
    assert a.endswith(b"\n")


def test_hash_entry_ignores_key_order() -> None:
    """Two entries with the same content in different key order hash equal."""
    a = {"kind": "x", "manifest_digest": "d", "prev_ledger_hash": GENESIS}
    b = {"prev_ledger_hash": GENESIS, "manifest_digest": "d", "kind": "x"}
    assert _hash_entry(a) == _hash_entry(b)


# ---------------------------------------------------------------------------
# CAS snapshot store
# ---------------------------------------------------------------------------


def test_store_snapshot_writes_once(tmp_path: Path) -> None:
    """Storing the same bytes twice does not rewrite the CAS file."""
    ledger = _mk_ledger(tmp_path)
    payload = dumps_jcs({"version": 1, "run_id": "abc"})
    d1 = ledger.store_snapshot(payload)
    mtime1 = ledger.snapshot_path_for(d1).stat().st_mtime_ns
    # Sleep briefly so a rewrite would produce a distinct mtime.
    time.sleep(0.01)
    d2 = ledger.store_snapshot(payload)
    mtime2 = ledger.snapshot_path_for(d2).stat().st_mtime_ns
    assert d1 == d2
    assert mtime1 == mtime2


def test_read_snapshot_round_trip(tmp_path: Path) -> None:
    """Bytes read back from the CAS match what was written."""
    ledger = _mk_ledger(tmp_path)
    payload = dumps_jcs({"version": 1, "run_id": "abc"})
    d = ledger.store_snapshot(payload)
    assert ledger.read_snapshot(d) == payload


def test_read_missing_snapshot_raises(tmp_path: Path) -> None:
    """Missing CAS entry raises the dedicated error type."""
    ledger = _mk_ledger(tmp_path)
    with pytest.raises(LedgerSnapshotMissingError):
        ledger.read_snapshot("0" * 64)


# ---------------------------------------------------------------------------
# Append + read-back parity
# ---------------------------------------------------------------------------


def test_append_and_iter_round_trip(tmp_path: Path) -> None:
    """A single append reads back with matching fields."""
    ledger = _mk_ledger(tmp_path)
    digest = _mk_digest(1)
    sig = _mk_signature(1)
    rid = _mk_run_id(1)
    result = ledger.append(
        manifest_digest=digest,
        rootknot_signature=sig,
        rootknot_run_id=rid,
    )
    assert isinstance(result, LedgerAppendResult)
    assert result.entry_index == 0
    assert not result.duplicate
    entries = ledger.load()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["manifest_digest"] == digest
    assert entry["rootknot_run_id"] == rid
    assert entry["prev_ledger_hash"] == GENESIS
    assert base64.b64decode(entry["rootknot_signature"]) == sig


def test_append_persists_via_fsync_before_return(tmp_path: Path) -> None:
    """The ledger file exists and is non-empty after append returns."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    assert ledger.ledger_path.exists()
    assert ledger.ledger_path.stat().st_size > 0


def test_append_with_manifest_bytes_writes_snapshot(tmp_path: Path) -> None:
    """When manifest_bytes is passed, the CAS file is populated + referenced."""
    ledger = _mk_ledger(tmp_path)
    payload = dumps_jcs({"version": 1, "run_id": "abc"})
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    ledger.append(
        manifest_digest=digest,
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
        manifest_bytes=payload,
    )
    entry = ledger.load()[0]
    assert entry["manifest_snapshot_ref"] == f"manifest_snapshots/{digest}.json"
    assert ledger.read_snapshot(digest) == payload


def test_append_refuses_mismatched_manifest_bytes(tmp_path: Path) -> None:
    """Bytes whose digest disagrees with the claimed digest are refused."""
    ledger = _mk_ledger(tmp_path)
    with pytest.raises(ValueError, match="hashes to a different digest"):
        ledger.append(
            manifest_digest=_mk_digest(1),  # not the digest of payload
            rootknot_signature=_mk_signature(1),
            rootknot_run_id=_mk_run_id(1),
            manifest_bytes=b"{}",
        )


def test_append_validates_digest_hex(tmp_path: Path) -> None:
    """Non-64-char / non-hex digests are refused before any I/O."""
    ledger = _mk_ledger(tmp_path)
    with pytest.raises(ValueError, match="64-char SHA-256 hex"):
        ledger.append(
            manifest_digest="short",
            rootknot_signature=_mk_signature(1),
            rootknot_run_id=_mk_run_id(1),
        )
    with pytest.raises(ValueError, match="not valid hex"):
        ledger.append(
            manifest_digest="Z" * 64,
            rootknot_signature=_mk_signature(1),
            rootknot_run_id=_mk_run_id(1),
        )


def test_append_validates_run_id(tmp_path: Path) -> None:
    """Empty run_id is refused."""
    ledger = _mk_ledger(tmp_path)
    with pytest.raises(ValueError, match="rootknot_run_id"):
        ledger.append(
            manifest_digest=_mk_digest(1),
            rootknot_signature=_mk_signature(1),
            rootknot_run_id="",
        )


# ---------------------------------------------------------------------------
# GENESIS + Merkle chain
# ---------------------------------------------------------------------------


def test_prev_ledger_hash_chain_links(tmp_path: Path) -> None:
    """Each entry's prev_ledger_hash equals the actual hash of the prior entry."""
    ledger = _mk_ledger(tmp_path)
    for i in range(5):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    entries = ledger.load()
    assert entries[0]["prev_ledger_hash"] == GENESIS
    for i in range(1, len(entries)):
        assert entries[i]["prev_ledger_hash"] == _hash_entry(entries[i - 1])


def test_verify_chain_clean(tmp_path: Path) -> None:
    """A fresh 5-entry ledger verifies cleanly."""
    ledger = _mk_ledger(tmp_path)
    for i in range(5):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    result = ledger.verify_chain()
    assert result.valid is True
    assert result.first_break_at is None
    assert result.tail_valid_count == 5


def test_verify_chain_empty(tmp_path: Path) -> None:
    """An empty ledger verifies cleanly with zero entries."""
    ledger = _mk_ledger(tmp_path)
    result = ledger.verify_chain()
    assert result.valid is True
    assert result.tail_valid_count == 0


def test_verify_chain_detects_middle_tamper(tmp_path: Path) -> None:
    """Mutating a middle entry breaks the chain at the NEXT entry."""
    ledger = _mk_ledger(tmp_path)
    for i in range(5):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    # Tamper: swap the run_id of the middle entry (index 2).
    raw = ledger.ledger_path.read_bytes()
    lines = raw.split(b"\n")
    # Skip trailing empty produced by final newline.
    body_lines = [ln for ln in lines if ln]
    entry = json.loads(body_lines[2])
    entry["rootknot_run_id"] = _mk_run_id(999)
    body_lines[2] = dumps_jcs(entry)
    ledger.ledger_path.write_bytes(b"\n".join(body_lines) + b"\n")

    result = ledger.verify_chain()
    assert result.valid is False
    # Entry 2 was mutated; entry 3's prev_ledger_hash now disagrees
    # with the actual hash of the mutated entry 2.
    assert result.first_break_at == 3
    assert result.tail_valid_count == 3


def test_verify_chain_detects_truncated_tail(tmp_path: Path) -> None:
    """Dropping the tail line still verifies (fewer entries)."""
    ledger = _mk_ledger(tmp_path)
    for i in range(5):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    # Drop the last complete line.
    raw = ledger.ledger_path.read_bytes()
    body_lines = [ln for ln in raw.split(b"\n") if ln]
    truncated = b"\n".join(body_lines[:-1]) + b"\n"
    ledger.ledger_path.write_bytes(truncated)

    result = ledger.verify_chain()
    assert result.valid is True
    assert result.tail_valid_count == 4  # exposes the drop


# ---------------------------------------------------------------------------
# Malformed lines
# ---------------------------------------------------------------------------


def test_middle_malformed_line_raises_corrupt(tmp_path: Path) -> None:
    """A malformed middle line raises LedgerCorruptError on iter."""
    ledger = _mk_ledger(tmp_path)
    for i in range(3):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    raw = ledger.ledger_path.read_bytes()
    body_lines = [ln for ln in raw.split(b"\n") if ln]
    body_lines[1] = b"{not valid json"
    ledger.ledger_path.write_bytes(b"\n".join(body_lines) + b"\n")
    with pytest.raises(LedgerCorruptError):
        ledger.load()


def test_truncated_tail_line_is_tolerated(tmp_path: Path, caplog) -> None:
    """A truncated tail line is skipped with a WARN, not raised."""
    ledger = _mk_ledger(tmp_path)
    for i in range(3):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    raw = ledger.ledger_path.read_bytes()
    ledger.ledger_path.write_bytes(raw + b'{"incomplete')
    with caplog.at_level("WARNING", logger="ract.security.manifest_ledger"):
        loaded = ledger.load()
    assert len(loaded) == 3
    assert any("truncated manifest_ledger tail" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_append_idempotent_within_run(tmp_path: Path) -> None:
    """Same (run_id, manifest_digest) appended twice writes once."""
    ledger = _mk_ledger(tmp_path)
    digest = _mk_digest(1)
    rid = _mk_run_id(1)
    first = ledger.append(
        manifest_digest=digest,
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=rid,
    )
    second = ledger.append(
        manifest_digest=digest,
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=rid,
    )
    assert first.entry_index == 0
    assert first.duplicate is False
    assert second.entry_index == 0
    assert second.duplicate is True
    assert first.entry_hash == second.entry_hash
    assert len(ledger.load()) == 1


def test_same_manifest_across_runs_gets_distinct_entries(tmp_path: Path) -> None:
    """Different runs observing the same manifest each get their own entry."""
    ledger = _mk_ledger(tmp_path)
    digest = _mk_digest(1)
    ledger.append(
        manifest_digest=digest,
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    ledger.append(
        manifest_digest=digest,
        rootknot_signature=_mk_signature(2),
        rootknot_run_id=_mk_run_id(2),
    )
    entries = ledger.load()
    assert len(entries) == 2
    assert entries[0]["rootknot_run_id"] != entries[1]["rootknot_run_id"]
    assert entries[0]["manifest_digest"] == entries[1]["manifest_digest"]


# ---------------------------------------------------------------------------
# Merkle proof
# ---------------------------------------------------------------------------


def test_proof_of_returns_expected_tail(tmp_path: Path) -> None:
    """The Merkle proof for entry 1 in a 4-entry ledger walks to the tail."""
    ledger = _mk_ledger(tmp_path)
    for i in range(4):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    proof = ledger.proof_of(1)
    assert isinstance(proof, MerkleProof)
    assert proof.target_index == 1
    assert len(proof.forward_hashes) == 2  # indexes 2 and 3
    entries = ledger.load()
    assert proof.target_hash == _hash_entry(entries[1])
    assert proof.tail_hash == _hash_entry(entries[3])


def test_proof_of_tail_entry_has_empty_forward(tmp_path: Path) -> None:
    """A proof for the tail entry has no forward hashes."""
    ledger = _mk_ledger(tmp_path)
    for i in range(3):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    proof = ledger.proof_of(2)
    assert proof.forward_hashes == ()
    assert proof.target_hash == proof.tail_hash


def test_proof_of_out_of_range(tmp_path: Path) -> None:
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    with pytest.raises(IndexError):
        ledger.proof_of(5)


def test_verify_proof_without_loader_now_raises(tmp_path: Path) -> None:
    """SP Q6 amendment: verify_proof without a loader raises (see amendment tests)."""
    ledger = _mk_ledger(tmp_path)
    for i in range(3):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    proof = ledger.proof_of(0)
    with pytest.raises(ValueError, match="verify_proof requires a loader"):
        ManifestLedger.verify_proof(proof)


def test_verify_proof_with_loader(tmp_path: Path) -> None:
    """Loader-based verification walks the full chain."""
    ledger = _mk_ledger(tmp_path)
    for i in range(4):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    entries = ledger.load()
    by_hash = {_hash_entry(e): e for e in entries}
    proof = ledger.proof_of(0)
    assert ManifestLedger.verify_proof(proof, loader=by_hash.get) is True


def test_verify_proof_detects_tampered_target(tmp_path: Path) -> None:
    """Mutating target_entry breaks the target_hash invariant (loader mode)."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    proof = ledger.proof_of(0)
    tampered_entry = dict(proof.target_entry)
    tampered_entry["rootknot_run_id"] = _mk_run_id(999)
    from dataclasses import replace

    tampered = replace(proof, target_entry=tampered_entry)
    # Provide a trivial loader; the target-hash mismatch is caught
    # BEFORE the loader is walked.
    assert ManifestLedger.verify_proof(tampered, loader=lambda _: {}) is False


# ---------------------------------------------------------------------------
# Ambient ledger + record_environment_attestation
# ---------------------------------------------------------------------------


class _StubKnot:
    """Minimal duck-type of Rootknot for observer testing."""

    def __init__(
        self,
        manifest_digest: bytes,
        environment_signature: bytes,
        run_id: str,
    ) -> None:
        self.manifest_digest = manifest_digest
        self.environment_signature = environment_signature
        self.run_id = run_id


def test_get_current_ledger_none_by_default() -> None:
    assert get_current_ledger() is None


def test_bind_ledger_scopes_ambient(tmp_path: Path) -> None:
    ledger = _mk_ledger(tmp_path)
    assert get_current_ledger() is None
    with bind_ledger(ledger) as bound:
        assert bound is ledger
        assert get_current_ledger() is ledger
    assert get_current_ledger() is None


def test_bind_ledger_refuses_non_ledger() -> None:
    with pytest.raises(TypeError):
        with bind_ledger(object()):  # type: ignore[arg-type]
            pass


def test_record_environment_attestation_skips_without_ambient(tmp_path: Path) -> None:
    knot = _StubKnot(
        manifest_digest=bytes.fromhex(_mk_digest(1)),
        environment_signature=_mk_signature(1),
        run_id=_mk_run_id(1),
    )
    # No ambient ledger bound -- helper returns None.
    assert record_environment_attestation(knot) is None


def test_record_environment_attestation_appends_via_ambient(tmp_path: Path) -> None:
    ledger = _mk_ledger(tmp_path)
    knot = _StubKnot(
        manifest_digest=bytes.fromhex(_mk_digest(1)),
        environment_signature=_mk_signature(1),
        run_id=_mk_run_id(1),
    )
    with bind_ledger(ledger):
        result = record_environment_attestation(knot)
    assert result is not None
    assert result.entry_index == 0
    entries = ledger.load()
    assert len(entries) == 1
    assert entries[0]["manifest_digest"] == _mk_digest(1)


def test_record_environment_attestation_skips_when_no_env_sig(tmp_path: Path) -> None:
    ledger = _mk_ledger(tmp_path)
    knot = _StubKnot(
        manifest_digest=bytes.fromhex(_mk_digest(1)),
        environment_signature=b"",
        run_id=_mk_run_id(1),
    )
    with bind_ledger(ledger):
        assert record_environment_attestation(knot) is None
    assert ledger.load() == []


def test_record_environment_attestation_skips_when_no_run_id(tmp_path: Path) -> None:
    ledger = _mk_ledger(tmp_path)
    knot = _StubKnot(
        manifest_digest=bytes.fromhex(_mk_digest(1)),
        environment_signature=_mk_signature(1),
        run_id="",
    )
    with bind_ledger(ledger):
        assert record_environment_attestation(knot) is None


def test_record_environment_attestation_skips_when_zero_manifest_digest(
    tmp_path: Path,
) -> None:
    ledger = _mk_ledger(tmp_path)
    knot = _StubKnot(
        manifest_digest=b"\x00" * 32,
        environment_signature=_mk_signature(1),
        run_id=_mk_run_id(1),
    )
    with bind_ledger(ledger):
        assert record_environment_attestation(knot) is None


# ---------------------------------------------------------------------------
# Tool-trace summariser
# ---------------------------------------------------------------------------


def test_summarise_tool_trace_from_dicts() -> None:
    events = [
        {"kind": "tool.called", "payload": {"tool_id": "grep"}, "timestamp_ns": 100},
        {"kind": "tool.called", "payload": {"tool_id": "read"}, "timestamp_ns": 200},
        {"kind": "step.started", "payload": {}, "timestamp_ns": 150},
        {"kind": "tool.called", "payload": {"tool_id": "grep"}, "timestamp_ns": 300},
    ]
    summary = summarise_tool_trace_from_events(events)
    assert summary["invocation_count"] == 3
    assert summary["tool_ids_invoked"] == ["grep", "read", "grep"]
    assert summary["first_invoke_at"] is not None
    assert summary["last_invoke_at"] is not None


def test_summarise_tool_trace_empty() -> None:
    summary = summarise_tool_trace_from_events([])
    assert summary["invocation_count"] == 0
    assert summary["tool_ids_invoked"] == []
    assert summary["first_invoke_at"] is None
    assert summary["last_invoke_at"] is None


# ---------------------------------------------------------------------------
# WAL cross-link
# ---------------------------------------------------------------------------


def test_count_wal_entries_uses_load_all(tmp_path: Path) -> None:
    """count_wal_entries returns snapshot+wal line counts from load_all."""
    from ract.core.assumptions_wal import AssumptionWal

    wal = AssumptionWal(tmp_path / "wal")
    assert count_wal_entries(wal) == 0
    wal.append("proposed", {"assumption_id": "a", "text": "t"})
    wal.append("accepted", {"assumption_id": "a"})
    assert count_wal_entries(wal) == 2


def test_count_wal_entries_none() -> None:
    assert count_wal_entries(None) == 0


def test_append_wal_cross_link_field(tmp_path: Path) -> None:
    """When wal seqs are passed, the entry carries wal_cross_link."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
        first_wal_seq=3,
        last_wal_seq=7,
    )
    entry = ledger.load()[0]
    assert entry["wal_cross_link"] == {"first_wal_seq": 3, "last_wal_seq": 7}


# ---------------------------------------------------------------------------
# Concurrent writer -- OS lock contended
# ---------------------------------------------------------------------------


def test_concurrent_writer_lock_contention(tmp_path: Path) -> None:
    """A held OS lock refuses a second append after the retry window."""
    ledger = _mk_ledger(tmp_path)
    # Seed with one entry so the file exists.
    ledger.append(
        manifest_digest=_mk_digest(0),
        rootknot_signature=_mk_signature(0),
        rootknot_run_id=_mk_run_id(0),
    )
    # Acquire the OS lock directly and hold it while a threaded append
    # attempts to run.
    holder_fd = os.open(
        ledger.ledger_path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0),
        0o644,
    )
    _lock_exclusive(holder_fd)
    error_holder: dict[str, BaseException | None] = {"exc": None}

    def _writer() -> None:
        # Bypass the in-process thread lock by using a fresh Ledger
        # instance (module_07 threading.Lock is per-instance).
        second = ManifestLedger(ledger._root)
        try:
            second.append(
                manifest_digest=_mk_digest(1),
                rootknot_signature=_mk_signature(1),
                rootknot_run_id=_mk_run_id(1),
            )
        except BaseException as exc:  # noqa: BLE001
            error_holder["exc"] = exc

    thread = threading.Thread(target=_writer)
    thread.start()
    thread.join(timeout=5)
    try:
        _unlock(holder_fd)
    finally:
        os.close(holder_fd)
    assert isinstance(error_holder["exc"], LedgerLockContended)


# ---------------------------------------------------------------------------
# Platform-skip smoke tests for the lock branches
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only fcntl path")
def test_posix_lock_branch_smoke(tmp_path: Path) -> None:
    """The POSIX ``fcntl.flock`` path acquires and releases without error."""
    ledger = _mk_ledger(tmp_path)
    ledger.ledger_path.touch()
    fd = os.open(ledger.ledger_path, os.O_WRONLY | os.O_APPEND)
    try:
        _lock_exclusive(fd)
        _unlock(fd)
    finally:
        os.close(fd)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only msvcrt path")
def test_windows_lock_branch_smoke(tmp_path: Path) -> None:
    """The Windows ``msvcrt.locking`` path acquires and releases without error."""
    ledger = _mk_ledger(tmp_path)
    ledger.ledger_path.touch()
    fd = os.open(
        ledger.ledger_path,
        os.O_WRONLY | os.O_APPEND | os.O_BINARY,
    )
    try:
        _lock_exclusive(fd)
        _unlock(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Kill-during-append recovery
# ---------------------------------------------------------------------------


def test_subprocess_kill_before_fsync_is_tolerated(tmp_path: Path) -> None:
    """A process kill mid-append leaves a truncated tail the reader recovers from."""
    # Build a healthy ledger with 2 entries.
    ledger = _mk_ledger(tmp_path)
    for i in range(2):
        ledger.append(
            manifest_digest=_mk_digest(i),
            rootknot_signature=_mk_signature(i),
            rootknot_run_id=_mk_run_id(i),
        )
    # Simulate a mid-write by appending a partial (non-JSON) tail.
    raw = ledger.ledger_path.read_bytes()
    ledger.ledger_path.write_bytes(raw + b'{"timestamp": "2026')
    # A fresh ledger instance loads and tolerates the truncated tail.
    fresh = ManifestLedger(ledger._root)
    entries = fresh.load()
    assert len(entries) == 2


# ---------------------------------------------------------------------------
# SP Q1 amendment -- verify_chain now also checks entry schema
# ---------------------------------------------------------------------------


def test_sp_q1_verify_chain_rejects_schema_invalid_entry(tmp_path: Path) -> None:
    """A rogue writer injecting a schema-invalid entry breaks verify_chain.

    Emulates the SP Q1 attacker: bypass the OS lock (which is advisory
    on POSIX), craft a JSON line with a CORRECTLY-linking
    ``prev_ledger_hash`` but a missing mandatory field. The prior
    verify_chain accepted this line; the amendment rejects it via
    ``_entry_schema_valid``.
    """
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(0),
        rootknot_signature=_mk_signature(0),
        rootknot_run_id=_mk_run_id(0),
    )
    # Compute correct prev hash and craft a schema-invalid entry.
    entries = ledger.load()
    prev_hash = _hash_entry(entries[-1])
    rogue = {
        # Missing rootknot_run_id + tool_trace_summary -- schema-invalid.
        "manifest_digest": _mk_digest(1),
        "rootknot_signature": base64.b64encode(_mk_signature(1)).decode("ascii"),
        "prev_ledger_hash": prev_hash,
    }
    with ledger.ledger_path.open("ab") as fh:
        fh.write(dumps_jcs(rogue) + b"\n")
    result = ledger.verify_chain()
    assert result.valid is False
    assert result.first_break_at == 1


def test_sp_q1_verify_chain_rejects_bad_base64_signature(tmp_path: Path) -> None:
    """A rogue entry with garbage base64 for rootknot_signature is rejected."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(0),
        rootknot_signature=_mk_signature(0),
        rootknot_run_id=_mk_run_id(0),
    )
    entries = ledger.load()
    prev_hash = _hash_entry(entries[-1])
    rogue = {
        "manifest_digest": _mk_digest(1),
        "rootknot_signature": "!!!not-base64!!!",
        "rootknot_run_id": _mk_run_id(1),
        "tool_trace_summary": {
            "tool_ids_invoked": [],
            "invocation_count": 0,
            "first_invoke_at": None,
            "last_invoke_at": None,
        },
        "prev_ledger_hash": prev_hash,
    }
    with ledger.ledger_path.open("ab") as fh:
        fh.write(dumps_jcs(rogue) + b"\n")
    result = ledger.verify_chain()
    assert result.valid is False
    assert result.first_break_at == 1


# ---------------------------------------------------------------------------
# SP Q3 amendment -- CAS tmp path is per-process/thread
# ---------------------------------------------------------------------------


def test_sp_q3_cas_race_uses_per_process_tmp(tmp_path: Path) -> None:
    """Two writers racing on the same digest do not corrupt the CAS file."""
    ledger = _mk_ledger(tmp_path)
    payload = dumps_jcs({"version": 1, "run_id": "abc"})
    barrier = threading.Barrier(4)
    results: list[str] = []

    def _writer() -> None:
        barrier.wait()
        results.append(ledger.store_snapshot(payload))

    threads = [threading.Thread(target=_writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    import hashlib

    expected_digest = hashlib.sha256(payload).hexdigest()
    assert all(r == expected_digest for r in results)
    assert ledger.snapshot_path_for(expected_digest).read_bytes() == payload


# ---------------------------------------------------------------------------
# SP Q5 amendment -- append refusal emits WARN + manifest.ledger.refused
# ---------------------------------------------------------------------------


class _CountingSink:
    """Test sink capturing (kind, payload) tuples for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(
        self,
        kind: str,
        payload: dict,
        *,
        step_id: bytes | None = None,
        parent_id: bytes | None = None,
        timestamp_ns: int | None = None,
    ) -> None:
        self.events.append((kind, dict(payload)))


def test_sp_q5_observer_emits_refused_event_on_append_failure(
    tmp_path: Path, caplog, monkeypatch
) -> None:
    """A ledger append failure emits manifest.ledger.refused + WARN log."""
    from ract.trace import sink as _sink_module

    sink = _CountingSink()
    orig_sink = _sink_module._sink
    _sink_module._sink = sink
    try:
        ledger = _mk_ledger(tmp_path)

        def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("disk full")

        monkeypatch.setattr(ledger, "append", _boom)
        knot = _StubKnot(
            manifest_digest=bytes.fromhex(_mk_digest(1)),
            environment_signature=_mk_signature(1),
            run_id=_mk_run_id(1),
        )
        with caplog.at_level("WARNING", logger="ract.security.manifest_ledger"):
            result = record_environment_attestation(knot, ledger=ledger)
        assert result is None
        assert any(
            "manifest_ledger append refused" in rec.message
            for rec in caplog.records
        )
        refused = [e for e in sink.events if e[0] == "manifest.ledger.refused"]
        assert len(refused) == 1
        payload = refused[0][1]
        assert payload["manifest_digest"] == _mk_digest(1)
        assert payload["run_id"] == _mk_run_id(1)
        assert payload["error_kind"] == "OSError"
    finally:
        _sink_module._sink = orig_sink


# ---------------------------------------------------------------------------
# SP Q6 amendment -- verify_proof requires a loader
# ---------------------------------------------------------------------------


def test_sp_q6_verify_proof_requires_loader(tmp_path: Path) -> None:
    """verify_proof without a loader now raises ValueError."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    proof = ledger.proof_of(0)
    with pytest.raises(ValueError, match="verify_proof requires a loader"):
        ManifestLedger.verify_proof(proof)


def test_sp_q6_verify_proof_shape_only_still_available(tmp_path: Path) -> None:
    """The structural-only check remains available under the honest name."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    proof = ledger.proof_of(0)
    assert ManifestLedger.verify_proof_shape_only(proof) is True


def test_sp_q6_verify_proof_shape_only_detects_target_tamper(tmp_path: Path) -> None:
    """Shape-only mode still catches target-entry tamper."""
    ledger = _mk_ledger(tmp_path)
    ledger.append(
        manifest_digest=_mk_digest(1),
        rootknot_signature=_mk_signature(1),
        rootknot_run_id=_mk_run_id(1),
    )
    proof = ledger.proof_of(0)
    from dataclasses import replace

    tampered = replace(
        proof, target_entry={**proof.target_entry, "rootknot_run_id": "z" * 32}
    )
    assert ManifestLedger.verify_proof_shape_only(tampered) is False


# RACT 0.5.1
