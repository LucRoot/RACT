"""WAL torn-pair regression: ``proposed`` replay must not regress terminals.

Lens D D3 identified that ``AssumptionRegistry._apply_wal_entry("proposed")``
unconditionally overwrote the in-memory state to PROPOSED, discarding
whichever terminal state (DISCHARGED / VIOLATED) the snapshot had
already hydrated. Under ``rotate_snapshot``'s documented "torn pair"
recovery (snapshot replaced but WAL not yet truncated), a re-play of
the original ``proposed`` line resets the assumption -- if a later
``discharged`` line survives, the state re-terminalises; if it does
NOT (WAL rewind, differential pruning, or truncated tail), the
registry silently ends up at PROPOSED after a run that had committed
to DISCHARGED.

This regression constructs the scenario directly: pre-populate the
snapshot with a DISCHARGED assumption + a lone ``proposed`` line in
the WAL for the same id. After the fix, the reload keeps DISCHARGED;
before the fix, it clobbers to PROPOSED.

Reference:
- ``_BUILD/audit_2026-08-21/lens_D_rootknot_signatures.md`` D3.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_02.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.core.assumption import AssumptionState, Evidence
from ract.core.assumption_registry import AssumptionRegistry
from ract.core.assumptions_wal import AssumptionWal


def test_wal_proposed_replay_does_not_regress_discharged(tmp_path: Path) -> None:
    """A snapshot-terminalised DISCHARGED survives a torn ``proposed`` replay."""
    # Seed via a first-life registry: propose + accept + discharge, rotate.
    r = AssumptionRegistry(wal_dir=tmp_path)
    a = r.propose("mission-critical assumption")
    r.accept(a.id)
    r.discharge(a.id, Evidence("verified end-to-end"))
    r.rotate_snapshot()

    # Confirm the pre-torn state: snapshot has the DISCHARGED record; WAL
    # is empty after rotate.
    snap_path = tmp_path / AssumptionWal.SNAPSHOT_NAME
    wal_path = tmp_path / AssumptionWal.WAL_NAME
    assert snap_path.exists() and snap_path.stat().st_size > 0
    assert wal_path.exists() and wal_path.stat().st_size == 0

    # Simulate the torn-pair window: an OLD ``proposed`` line for the same
    # assumption id lands in the WAL after the snapshot was written but
    # before the WAL was truncated (in a crash the two-step is not atomic,
    # so a stale WAL can carry pre-rotate transitions on the next reload).
    # We emulate this by appending the raw ``proposed`` line the registry
    # would have written at t0.
    torn_line = {
        "assumption_id": a.id.hex(),
        "digest": a.digest.hex(),
        "text": "mission-critical assumption",
        "depends_on": [],
        "kind": "proposed",
    }
    wal_path.write_bytes((json.dumps(torn_line, sort_keys=True) + "\n").encode("utf-8"))

    # Reload: the snapshot must dominate. Before the D3 fix, the ``proposed``
    # replay resets state to PROPOSED. After the fix, terminal state wins.
    r2 = AssumptionRegistry(wal_dir=tmp_path)
    reloaded = r2.get(a.id)
    assert reloaded is not None
    assert reloaded.state == AssumptionState.DISCHARGED, (
        "torn ``proposed`` replay regressed the DISCHARGED terminal to "
        f"{reloaded.state} -- Lens D D3 regression."
    )


def test_wal_proposed_replay_does_not_regress_violated(tmp_path: Path) -> None:
    """A snapshot-terminalised VIOLATED also survives a torn replay."""
    from ract.core.assumption import Violation

    r = AssumptionRegistry(wal_dir=tmp_path)
    a = r.propose("risky claim")
    r.accept(a.id)
    r.violate(a.id, Violation("counterexample discovered"))
    r.rotate_snapshot()

    wal_path = tmp_path / AssumptionWal.WAL_NAME
    torn_line = {
        "assumption_id": a.id.hex(),
        "digest": a.digest.hex(),
        "text": "risky claim",
        "depends_on": [],
        "kind": "proposed",
    }
    wal_path.write_bytes((json.dumps(torn_line, sort_keys=True) + "\n").encode("utf-8"))

    r2 = AssumptionRegistry(wal_dir=tmp_path)
    reloaded = r2.get(a.id)
    assert reloaded is not None
    assert reloaded.state == AssumptionState.VIOLATED


def test_wal_proposed_replay_still_idempotent_for_unseen_id(tmp_path: Path) -> None:
    """A ``proposed`` line for an unseen id still lands as PROPOSED."""
    # No snapshot yet; a fresh ``proposed`` WAL line hydrates the id.
    r = AssumptionRegistry(wal_dir=tmp_path)
    fresh = r.propose("fresh id")
    # State check via reload.
    r2 = AssumptionRegistry(wal_dir=tmp_path)
    reloaded = r2.get(fresh.id)
    assert reloaded is not None
    assert reloaded.state == AssumptionState.PROPOSED
