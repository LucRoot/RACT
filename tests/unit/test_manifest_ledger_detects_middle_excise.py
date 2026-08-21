"""Regression: :meth:`ManifestLedger.verify_chain` MUST detect a
middle-excise tamper -- an attacker who removes middle entries and
recomputes the downstream ``prev_ledger_hash`` values to re-link the
chain.

v0.5.1 module_09 (Lens F H4 closure). Prior behavior: the verifier
only checked that ``entries[i]["prev_ledger_hash"] == hash(entries[i-1])``.
A skilled attacker with file-write access could excise entries 4..6,
recompute the ``prev_ledger_hash`` on entries 7..N to reference the
new prior, and the chain would verify as ``valid=True`` -- the
"excise + recompute" surface was left open.

Fix: every new append stamps an ``entry_index`` into its payload
(covered by :func:`_hash_entry`). The verifier checks that each
entry's stamped ``entry_index`` equals its physical position in the
ledger. Excising the middle changes positions but the stamped
indexes stay the same -- the density check fires.

Reference:
- ``_BUILD/audit_2026-08-21/lens_F_trace_events_ledgers.md`` H4.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_09.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.security.manifest_ledger import (
    ManifestLedger,
    _canonical_line,
    _hash_entry,
)


def _seed_ten_entries(tmp_path: Path) -> tuple[ManifestLedger, list[dict]]:
    """Append 10 legitimate observations; return the ledger + parsed entries."""
    ledger = ManifestLedger(tmp_path)
    for i in range(10):
        digest = f"{i:064x}"
        ledger.append(
            manifest_digest=digest,
            rootknot_signature=(f"sig-{i}".encode() + b"\x00" * 16)[:32],
            rootknot_run_id=f"run-{i}",
        )
    entries = ledger.load()
    assert len(entries) == 10
    return ledger, entries


def test_middle_excise_with_recomputed_prev_hash_is_detected(
    tmp_path: Path,
) -> None:
    """Excise entries 4..6, recompute ``prev_ledger_hash`` on entries
    7..9 to re-link the chain naively, and verify that
    :meth:`verify_chain` still returns ``valid=False``.
    """
    ledger, entries = _seed_ten_entries(tmp_path)

    # Baseline: full chain verifies.
    baseline = ledger.verify_chain()
    assert baseline.valid, "baseline chain must be valid"
    assert baseline.tail_valid_count == 10

    # Construct the tampered ledger on disk: keep entries 0..3, drop
    # entries 4..6, keep entries 7..9 with recomputed prev_ledger_hash.
    kept = list(entries[:4])
    prev_hash = _hash_entry(entries[3])  # tail of kept prefix
    for i in (7, 8, 9):
        forged = dict(entries[i])
        forged["prev_ledger_hash"] = prev_hash
        # NOTE: attacker does NOT rewrite entry_index. Rewriting it
        # would break the chain differently (canonical bytes change
        # → prev_ledger_hash on the next entry no longer matches),
        # forcing the attacker to forge a full new chain rather
        # than simply excise. Keeping the stamped index is the
        # "cheap excise" the H4 finding warned about.
        kept.append(forged)
        prev_hash = _hash_entry(forged)

    ledger_path = tmp_path / ManifestLedger.LEDGER_NAME
    with open(ledger_path, "wb") as fh:
        for entry in kept:
            fh.write(_canonical_line(entry))

    # Verify: MUST return valid=False. The first break is at
    # physical position 4 (kept[4]), whose stamped entry_index is 7.
    result = ledger.verify_chain()
    assert not result.valid, (
        "middle-excise MUST be detected -- verify_chain claimed valid"
    )
    assert result.first_break_at == 4
    assert result.tail_valid_count == 4


def test_prehistoric_entries_without_entry_index_still_verify(
    tmp_path: Path,
) -> None:
    """Backward-compat: entries written before module_09 do NOT carry
    ``entry_index``. :meth:`verify_chain` MUST still accept them (the
    density check is skipped for missing stamps).
    """
    # Simulate a pre-module_09 ledger by hand-writing entries without
    # entry_index but with a valid prev_ledger_hash chain.
    from ract.security.manifest_ledger import (
        GENESIS,
        _build_entry,
    )

    ledger = ManifestLedger(tmp_path)
    entries: list[dict] = []
    prev = GENESIS
    for i in range(5):
        entry = _build_entry(
            timestamp="2026-08-21T00:00:00Z",
            manifest_digest=f"{i:064x}",
            manifest_snapshot_ref=None,
            rootknot_signature=(f"sig-{i}".encode() + b"\x00" * 16)[:32],
            rootknot_run_id=f"run-{i}",
            tool_trace_summary={
                "tool_ids_invoked": [],
                "invocation_count": 0,
                "first_invoke_at": None,
                "last_invoke_at": None,
            },
            first_wal_seq=None,
            last_wal_seq=None,
            prev_ledger_hash=prev,
            entry_index=i,
        )
        # Strip entry_index to simulate a pre-module_09 file (the
        # prev_hash chain then needs to be recomputed against the
        # stripped entry).
        del entry["entry_index"]
        entries.append(entry)
        prev = _hash_entry(entry)

    ledger_path = tmp_path / ManifestLedger.LEDGER_NAME
    with open(ledger_path, "wb") as fh:
        for entry in entries:
            fh.write(_canonical_line(entry))

    result = ledger.verify_chain()
    assert result.valid, (
        "legacy entries without entry_index must still verify "
        "(backward-compat surface)"
    )
    assert result.tail_valid_count == 5


def test_entry_index_stamped_at_append(tmp_path: Path) -> None:
    """Sanity: every entry appended via :meth:`ManifestLedger.append`
    carries the correct stamped ``entry_index``.
    """
    _, entries = _seed_ten_entries(tmp_path)
    for i, entry in enumerate(entries):
        assert entry.get("entry_index") == i, (
            f"entry {i} missing or wrong entry_index: {entry.get('entry_index')!r}"
        )
