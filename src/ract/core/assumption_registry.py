"""AssumptionRegistry with violation propagation.

v0.5.1 module_01 (external-review response) adds an optional
crash-consistency WAL under ``wal_dir``. When ``wal_dir`` is set, every
state transition (``proposed`` / ``accepted`` / ``discharged`` /
``violated``) hits disk via :class:`~ract.core.assumptions_wal.AssumptionWal`
with ``fsync`` before the in-memory mutation, and the registry can
reload losslessly after a process kill. When ``wal_dir`` is ``None``
(the default), the registry runs pure-in-memory as it did in v0.5.0 —
every existing call-site keeps working unchanged.

The four-transition WAL vocabulary lives in
:data:`ract.core.assumptions_wal.TRANSITIONS`; the four matching
trace events (``assumption.proposed`` / ``.accepted`` / ``.discharged``
/ ``.violated``) land in :data:`ract.trace.events.EventKind`.

Reference: DEEPSEEK_REVIEW_5.md §"G1 deeper dive" and
``_BUILD/ract_v0.5.1_external_review_response/module_01.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from ract.core.assumption import (
    Assumed,
    Assumption,
    AssumptionId,
    AssumptionState,
    Evidence,
    Violation,
)
from ract.core.assumptions_wal import AssumptionWal, TRANSITIONS, WalEntry
from ract.core.types import AssumptionId as _AssumptionIdType  # re-export shortcut


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class AssumptionRegistry:
    """Single source of truth for assumption lifecycle.

    Set ``wal_dir`` to a directory path (typically ``<workspace>/.ract``)
    to enable the crash-consistency WAL. On construction with a set
    ``wal_dir`` the registry loads any pre-existing
    ``assumptions.json`` snapshot and replays the ``assumptions.wal``
    tail before returning. Leave ``wal_dir=None`` (the default) for
    the v0.5.0 pure-in-memory behavior — every existing test-site
    that constructs ``AssumptionRegistry()`` keeps working unchanged.
    """

    _assumptions: dict[AssumptionId, Assumption] = field(default_factory=dict)
    wal_dir: Path | None = None
    _wal: AssumptionWal | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.wal_dir is not None:
            self._wal = AssumptionWal(Path(self.wal_dir))
            self._reload_from_disk()

    # ------------------------------------------------------------------
    # Public API — every mutator persists BEFORE mutating memory
    # ------------------------------------------------------------------

    def propose(
        self, text: str, depends_on: tuple[AssumptionId, ...] = ()
    ) -> Assumption:
        """Propose a new assumption and return it."""
        assumption = Assumption.propose(text, depends_on)
        self._persist(
            "proposed",
            {
                "assumption_id": assumption.id.hex(),
                "digest": assumption.digest.hex(),
                "text": text,
                "depends_on": [d.hex() for d in depends_on],
            },
        )
        self._assumptions[assumption.id] = assumption
        _emit_assumption_event(
            "assumption.proposed",
            {
                "assumption_id": assumption.id.hex(),
                "digest": assumption.digest.hex(),
                "text": text,
            },
        )
        return assumption

    def accept(self, assumption_id: AssumptionId) -> Assumption:
        """Move a PROPOSED assumption to ACTIVE."""
        assumption = self._get(assumption_id)
        if assumption.state != AssumptionState.PROPOSED:
            raise ValueError(f"assumption {assumption_id.hex()} is not proposed")
        self._persist(
            "accepted",
            {
                "assumption_id": assumption_id.hex(),
                "digest": assumption.digest.hex(),
            },
        )
        updated = Assumption(
            id=assumption.id,
            text=assumption.text,
            digest=assumption.digest,
            state=AssumptionState.ACTIVE,
            depends_on=assumption.depends_on,
        )
        self._assumptions[assumption_id] = updated
        _emit_assumption_event(
            "assumption.accepted",
            {
                "assumption_id": assumption_id.hex(),
                "digest": assumption.digest.hex(),
            },
        )
        return updated

    def discharge(self, assumption_id: AssumptionId, evidence: Evidence) -> Assumption:
        """Discharge an ACTIVE assumption with evidence."""
        assumption = self._get(assumption_id)
        if assumption.state not in (AssumptionState.ACTIVE, AssumptionState.PROPOSED):
            raise ValueError(f"assumption {assumption_id.hex()} cannot be discharged")
        self._persist(
            "discharged",
            {
                "assumption_id": assumption_id.hex(),
                "digest": assumption.digest.hex(),
                "evidence": _evidence_payload(evidence),
            },
        )
        updated = Assumption(
            id=assumption.id,
            text=assumption.text,
            digest=assumption.digest,
            state=AssumptionState.DISCHARGED,
            depends_on=assumption.depends_on,
            discharged_by=evidence,
        )
        self._assumptions[assumption_id] = updated
        _emit_assumption_event(
            "assumption.discharged",
            {
                "assumption_id": assumption_id.hex(),
                "digest": assumption.digest.hex(),
            },
        )
        return updated

    def violate(
        self, assumption_id: AssumptionId, violation: Violation
    ) -> list[AssumptionId]:
        """Mark an assumption VIOLATED and propagate to all dependents.

        Returns the list of assumption IDs that were marked violated.
        The WAL records only the root ``violated`` transition and its
        ``violation`` body; dependency propagation is deterministic
        given the current graph and is recomputed at replay time.
        """
        assumption = self._get(assumption_id)
        if assumption.state == AssumptionState.VIOLATED:
            return []
        self._persist(
            "violated",
            {
                "assumption_id": assumption_id.hex(),
                "digest": assumption.digest.hex(),
                "violation": _violation_payload(violation),
            },
        )
        updated = Assumption(
            id=assumption.id,
            text=assumption.text,
            digest=assumption.digest,
            state=AssumptionState.VIOLATED,
            depends_on=assumption.depends_on,
            discharged_by=assumption.discharged_by,
            violated_by=violation,
        )
        self._assumptions[assumption_id] = updated
        violated: list[AssumptionId] = [assumption_id]

        # Propagate through the dependency graph.
        frontier = {assumption_id}
        while frontier:
            current = frontier.pop()
            for candidate in self._assumptions.values():
                if candidate.state == AssumptionState.VIOLATED:
                    continue
                if current in candidate.depends_on:
                    frontier.add(candidate.id)
                    self._assumptions[candidate.id] = Assumption(
                        id=candidate.id,
                        text=candidate.text,
                        digest=candidate.digest,
                        state=AssumptionState.VIOLATED,
                        depends_on=candidate.depends_on,
                        discharged_by=candidate.discharged_by,
                        violated_by=violation,
                    )
                    violated.append(candidate.id)
        for vid in violated:
            _emit_assumption_event(
                "assumption.violated",
                {
                    "assumption_id": vid.hex(),
                    "root_id": assumption_id.hex(),
                },
            )
        return violated

    def get(self, assumption_id: AssumptionId) -> Assumption | None:
        """Return the assumption or None."""
        return self._assumptions.get(assumption_id)

    def violated(self) -> list[Assumption]:
        """Return every assumption currently in the VIOLATED state."""
        return [
            assumption
            for assumption in self._assumptions.values()
            if assumption.state == AssumptionState.VIOLATED
        ]

    def invalid_assumed(self, assumed_items: list[Assumed]) -> list[Assumed]:
        """Return every Assumed whose assumption is not active/discharged."""
        return [item for item in assumed_items if not item.is_valid(self)]

    # ------------------------------------------------------------------
    # WAL rotation — public knob for the loop controller
    # ------------------------------------------------------------------

    def rotate_snapshot(self) -> None:
        """Write current registry state to the snapshot and truncate WAL.

        No-op when ``wal_dir`` is ``None``. The loop controller (or a
        periodic scheduler) calls this to keep the WAL bounded. After
        a successful rotation the WAL is 0 bytes on disk and the
        snapshot contains every current assumption as a single
        canonical line per assumption.
        """
        if self._wal is None:
            return
        entries = [self._snapshot_entry(a) for a in self._assumptions.values()]
        self._wal.rotate_snapshot(entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist(self, kind: str, payload: dict[str, Any]) -> None:
        """Append one transition to the WAL under fsync. No-op if no WAL.

        v0.5.1 module_06: when the ambient run_id
        (:func:`ract.runtime.get_current_run_id`) is set and the payload
        does not already carry a ``run_id`` field, the ambient value is
        stamped in so downstream replay + audit can join WAL entries to
        the run's Rootknots, event log lines, WorkspaceDigestChain
        edges, and SuiteChain entries by string equality. Payloads that
        already carry a ``run_id`` (explicit caller wiring) are
        preserved verbatim.

        SP Q2 amendment (external reviewer PARTIAL verdict): when the
        payload already carries a ``run_id`` that DIFFERS from the
        ambient value, a WARN is emitted so audit tooling can flag the
        divergence. The explicit value still wins (breaking that would
        break every test that hand-crafts a WAL payload), but the
        divergence is no longer silent.
        """
        if self._wal is None:
            return
        if kind not in TRANSITIONS:
            raise ValueError(f"unknown transition kind {kind!r}")
        from ract.runtime import get_current_run_id

        ambient = get_current_run_id()
        if "run_id" not in payload:
            if ambient is not None:
                payload = {**payload, "run_id": ambient}
        else:
            explicit = payload.get("run_id")
            if ambient is not None and explicit != ambient:
                import logging as _logging

                _logging.getLogger("ract.core.assumption_registry").warning(
                    "WAL %s entry carries explicit run_id %r that differs "
                    "from bound ambient run_id %r; explicit wins but audit "
                    "tooling should flag the split (SP Q2 amendment).",
                    kind,
                    explicit,
                    ambient,
                )
        self._wal.append(kind, payload)

    def _reload_from_disk(self) -> None:
        """Replay snapshot + WAL to reconstruct :attr:`_assumptions`.

        Called from ``__post_init__`` when ``wal_dir`` is set. Applies
        snapshot entries first, then WAL entries in append order.
        Dependency propagation for ``violated`` transitions is
        recomputed live — the WAL only records the root.

        SP Q5 amendment (external reviewer DEFECT verdict): when the
        ambient run_id is bound at reload time AND the on-disk WAL
        carries entries missing a ``run_id`` field, emit a WARN. This
        surfaces the "mixed with-rid / without-rid" mosaic condition
        so audit tooling can decide whether to trigger a rid-backfill
        (v0.6 flagged gap). Silent success on mixed files was the
        original defect -- the audit trail could not claim
        "all entries came from run X".
        """
        assert self._wal is not None
        snapshot_entries, wal_entries = self._wal.load_all()
        # Snapshot entries are already terminal-state per-assumption
        # dumps; hydrate them directly.
        for entry in snapshot_entries:
            self._hydrate_snapshot_entry(entry)
        for entry in wal_entries:
            self._apply_wal_entry(entry)
        # SP Q5 amendment: mixed-rid detection + WARN.
        from ract.runtime import get_current_run_id

        ambient = get_current_run_id()
        if ambient is not None:
            missing_indices = [
                idx
                for idx, entry in enumerate(wal_entries)
                if "run_id" not in entry.payload
            ]
            if missing_indices:
                import logging as _logging

                _logging.getLogger("ract.core.assumption_registry").warning(
                    "WAL reload under ambient run_id %r found %d legacy "
                    "entries without run_id (indices %r). Audit tooling "
                    "cannot claim 'all entries came from run %r' until a "
                    "backfill runs (v0.6 flagged gap). SP Q5 amendment.",
                    ambient,
                    len(missing_indices),
                    missing_indices[:5],
                    ambient,
                )

    def _hydrate_snapshot_entry(self, entry: WalEntry) -> None:
        payload = entry.payload
        aid = AssumptionId(bytes.fromhex(payload["assumption_id"]))
        depends_on = tuple(
            AssumptionId(bytes.fromhex(h)) for h in payload.get("depends_on", ())
        )
        state = AssumptionState(payload["state"])
        from ract.core.types import Digest

        digest = Digest(bytes.fromhex(payload["digest"]))
        discharged_by = _evidence_from_payload(payload.get("discharged_by"))
        violated_by = _violation_from_payload(payload.get("violated_by"))
        self._assumptions[aid] = Assumption(
            id=aid,
            text=payload["text"],
            digest=digest,
            state=state,
            depends_on=depends_on,
            discharged_by=discharged_by,
            violated_by=violated_by,
        )

    def _apply_wal_entry(self, entry: WalEntry) -> None:
        payload = entry.payload
        kind = entry.kind
        aid = AssumptionId(bytes.fromhex(payload["assumption_id"]))
        from ract.core.types import Digest

        if kind == "proposed":
            # v0.5.1 wiring module_02 (Lens D D3): torn-pair recovery
            # invariant. ``rotate_snapshot``'s crash-window (snapshot
            # replaced but WAL not yet truncated) can re-play a
            # historic ``proposed`` line after the snapshot has already
            # hydrated the assumption at a TERMINAL state (DISCHARGED
            # or VIOLATED) or the ACTIVE intermediate state. The
            # earlier writer unconditionally overwrote the state to
            # PROPOSED, silently regressing the terminal record.
            # Guard: skip the write when ``aid`` is already at a
            # non-PROPOSED state; the earlier terminal record wins
            # and the WAL replay stays idempotent for re-propose of
            # a never-terminalised id.
            existing = self._assumptions.get(aid)
            if existing is not None and existing.state in (
                AssumptionState.ACTIVE,
                AssumptionState.DISCHARGED,
                AssumptionState.VIOLATED,
            ):
                return
            digest = Digest(bytes.fromhex(payload["digest"]))
            depends_on = tuple(
                AssumptionId(bytes.fromhex(h)) for h in payload.get("depends_on", ())
            )
            self._assumptions[aid] = Assumption(
                id=aid,
                text=payload["text"],
                digest=digest,
                state=AssumptionState.PROPOSED,
                depends_on=depends_on,
            )
        elif kind == "accepted":
            existing = self._assumptions.get(aid)
            if existing is None:
                # Torn history: accept for an unknown id. Skip
                # defensively rather than raise — the snapshot may
                # have already terminalised this record.
                return
            self._assumptions[aid] = Assumption(
                id=existing.id,
                text=existing.text,
                digest=existing.digest,
                state=AssumptionState.ACTIVE,
                depends_on=existing.depends_on,
                discharged_by=existing.discharged_by,
                violated_by=existing.violated_by,
            )
        elif kind == "discharged":
            existing = self._assumptions.get(aid)
            if existing is None:
                return
            evidence = _evidence_from_payload(payload.get("evidence"))
            self._assumptions[aid] = Assumption(
                id=existing.id,
                text=existing.text,
                digest=existing.digest,
                state=AssumptionState.DISCHARGED,
                depends_on=existing.depends_on,
                discharged_by=evidence,
                violated_by=existing.violated_by,
            )
        elif kind == "violated":
            existing = self._assumptions.get(aid)
            if existing is None:
                return
            violation = _violation_from_payload(payload.get("violation"))
            # Mark this assumption VIOLATED and propagate to dependents.
            self._assumptions[aid] = Assumption(
                id=existing.id,
                text=existing.text,
                digest=existing.digest,
                state=AssumptionState.VIOLATED,
                depends_on=existing.depends_on,
                discharged_by=existing.discharged_by,
                violated_by=violation,
            )
            frontier = {aid}
            while frontier:
                current = frontier.pop()
                for candidate in list(self._assumptions.values()):
                    if candidate.state == AssumptionState.VIOLATED:
                        continue
                    if current in candidate.depends_on:
                        frontier.add(candidate.id)
                        self._assumptions[candidate.id] = Assumption(
                            id=candidate.id,
                            text=candidate.text,
                            digest=candidate.digest,
                            state=AssumptionState.VIOLATED,
                            depends_on=candidate.depends_on,
                            discharged_by=candidate.discharged_by,
                            violated_by=violation,
                        )
        else:  # pragma: no cover — TRANSITIONS is closed at write time
            raise ValueError(f"unknown WAL kind {kind!r}")

    def _snapshot_entry(self, assumption: Assumption) -> dict[str, Any]:
        """Return the canonical snapshot dict for one assumption."""
        payload: dict[str, Any] = {
            "assumption_id": assumption.id.hex(),
            "digest": assumption.digest.hex(),
            "text": assumption.text,
            "state": assumption.state.value,
            "depends_on": [d.hex() for d in assumption.depends_on],
        }
        if assumption.discharged_by is not None:
            payload["discharged_by"] = _evidence_payload(assumption.discharged_by)
        if assumption.violated_by is not None:
            payload["violated_by"] = _violation_payload(assumption.violated_by)
        # Snapshot entries reuse the WAL parser; ``kind`` here just
        # marks the snapshot-line schema (not a transition). Reload
        # dispatches on ``state`` inside the payload, not on ``kind``.
        payload["kind"] = "proposed"
        return payload

    def _get(self, assumption_id: AssumptionId) -> Assumption:
        assumption = self._assumptions.get(assumption_id)
        if assumption is None:
            raise KeyError(f"assumption {assumption_id.hex()} not found")
        return assumption


T = TypeVar("T")


# ---------------------------------------------------------------------------
# Payload helpers — Evidence / Violation round-trip
# ---------------------------------------------------------------------------


def _evidence_payload(evidence: Evidence) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": evidence.text}
    if evidence.artifact_digest is not None:
        payload["artifact_digest"] = evidence.artifact_digest.hex()
    return payload


def _evidence_from_payload(payload: dict[str, Any] | None) -> Evidence | None:
    if payload is None:
        return None
    from ract.core.types import Digest

    digest_hex = payload.get("artifact_digest")
    return Evidence(
        text=payload["text"],
        artifact_digest=Digest(bytes.fromhex(digest_hex)) if digest_hex else None,
    )


def _violation_payload(violation: Violation) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": violation.text}
    if violation.artifact_digest is not None:
        payload["artifact_digest"] = violation.artifact_digest.hex()
    return payload


def _violation_from_payload(payload: dict[str, Any] | None) -> Violation | None:
    if payload is None:
        return None
    from ract.core.types import Digest

    digest_hex = payload.get("artifact_digest")
    return Violation(
        text=payload["text"],
        artifact_digest=Digest(bytes.fromhex(digest_hex)) if digest_hex else None,
    )


def _emit_assumption_event(kind: str, payload: dict) -> None:
    """Emit an assumption lifecycle event to the event log.

    module_05 (SUBSTRATE §6.3). Local import so the assumption module
    stays trace-independent at import time.
    """
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(kind, payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pass


def bind_assumption(value: T, registry: AssumptionRegistry, text: str) -> Assumed[T]:
    """Lift ``value`` into an Assumed[T] backed by a new registry assumption."""
    assumption = registry.propose(text)
    registry.accept(assumption.id)
    return Assumed(value=value, assumption_id=assumption.id)


# Re-export shortcut kept for any downstream module that reached in.
__all__ = ["AssumptionRegistry", "bind_assumption", "_AssumptionIdType"]

# RACT 0.5.1
