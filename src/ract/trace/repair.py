"""Deterministic + idempotent event-log repair.

v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Implements the
"repair" primitive described in 04-RACT-DESIGN §5.1.3 -- reconstruct a
coherent event stream from a possibly-truncated or corrupted log by
synthesizing close events for open handles.

The design is inference-provider-independent; it operates entirely on
RACT's closed :class:`ract.trace.events.EventKind` vocabulary and
never crosses the closed-IP boundary named in the source-spec audit
(Lens 2 Delta 1, write-first invariant + repair; see the
``_BUILD/audit_2026-08-21c/`` bundle for the full derivation).

Open-handle detection uses RACT's existing closed EventKind vocabulary
(``ract.trace.events.EventKind``) -- no schema bump this module. The
mapping between open and synthesized close kinds:

- ``run.started`` (no ``run.completed`` / ``run.aborted``)
  -> synth ``run.aborted`` (reason="interrupted")
- ``step.started`` (no ``step.committed`` / ``step.rolled_back``)
  -> synth ``step.rolled_back`` (reason="interrupted")
- ``tool.called`` (no ``tool.result`` / ``tool.refused``)
  -> synth ``tool.result`` (status="unknown", reason="interrupted")
- ``prompt.sent`` (no ``response.received`` / ``response.rejected``)
  -> synth ``response.received`` (status="timed_out", reason="interrupted")
- ``handshake.requested`` (no ``handshake.resolved``)
  -> synth ``handshake.resolved`` (resolution="interrupted")

Every synthesized event carries ``payload["synthesized"] = True`` +
``payload["reason"]`` naming the repair cause + ``payload["source_event_id"]``
pointing at the open event, so downstream consumers can distinguish
synthesized closes from real ones.

Determinism + idempotence contract:

- ``repair(x)`` returns the same output on repeated calls given the same
  input (byte-identical events, byte-identical hashes).
- ``repair(repair(x)) == repair(x)``. The synthesized close events pair
  with the opens on the second pass; no additional closes are generated.

Determinism is achieved by deriving synthesized event ids from
``sha256(marker || open_event.id || close_kind_bytes)[:16]`` and
synthesized timestamps as ``open.timestamp_ns + 1``.

Fiber-lifecycle event kinds (``fiber.activated`` etc.) are intentionally
NOT synthesized here; per the audit's Delta 1 sketch and non-adoption of
§5.2, fibers are not a RACT primitive at v0.5.1.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from ract.trace.events import (
    Event,
    EventChain,
    EventKind,
    hash_event,
    new_event_id,  # noqa: F401 -- documented alt to synth id derivation
)

_LOG = logging.getLogger("ract.trace.repair")


# Marker prefix for deterministic synth id derivation. Any change to
# this constant is a repair-vocabulary schema bump because it changes
# the ids of ALL synthesized close events across ALL logs.
_SYNTH_MARKER: bytes = b"ract.trace.repair.synth.v1"


# Open-kind -> (close-kind, close-payload-template) map. The payload
# template is merged with ``{"synthesized": True, "reason":
# "interrupted", "source_event_id": <open_hex>}`` at synthesis time.
_CLOSE_MAP: dict[str, tuple[str, dict[str, Any]]] = {
    "run.started": ("run.aborted", {}),
    "step.started": ("step.rolled_back", {}),
    "tool.called": ("tool.result", {"status": "unknown"}),
    "prompt.sent": ("response.received", {"status": "timed_out"}),
    "handshake.requested": ("handshake.resolved", {"resolution": "interrupted"}),
}

# Kinds that CLOSE their respective open kind. When we encounter one of
# these, we remove the paired open from the "still open" set.
_CLOSE_KINDS: dict[str, str] = {
    "run.completed": "run.started",
    "run.aborted": "run.started",
    "step.committed": "step.started",
    "step.rolled_back": "step.started",
    "tool.result": "tool.called",
    "tool.refused": "tool.called",
    "response.received": "prompt.sent",
    "response.rejected": "prompt.sent",
    "handshake.resolved": "handshake.requested",
}


# ---------------------------------------------------------------------------
# Result value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairSummary:
    """Counts + reasons produced by one :func:`repair` invocation.

    Fields:

    - ``synthesized_count``: number of close events synthesized.
    - ``dropped_count``: number of input events dropped as
      semantically-incoherent (empty in practice today -- the reader
      handles byte-level tail truncation).
    - ``closed_kinds``: histogram ``{open_kind: count}`` naming which
      open kinds were closed.
    - ``dropped_reasons``: histogram ``{reason: count}``.
    - ``already_closed``: True if the input had no open handles
      (repair was a no-op; the log was already coherent).
    """

    synthesized_count: int
    dropped_count: int
    closed_kinds: dict[str, int]
    dropped_reasons: dict[str, int]
    already_closed: bool


@dataclass(frozen=True)
class RepairedEventStream:
    """The output of :func:`repair`.

    Fields:

    - ``events``: the full repaired event list (input events kept +
      synthesized closes appended).
    - ``synthesized_close_events``: subset of ``events`` added by
      repair.
    - ``dropped_events``: subset of the INPUT removed by repair
      (empty in practice today).
    - ``repair_summary``: :class:`RepairSummary` counts.
    """

    events: list[Event]
    synthesized_close_events: list[Event]
    dropped_events: list[Event] = field(default_factory=list)
    repair_summary: RepairSummary = field(
        default_factory=lambda: RepairSummary(
            synthesized_count=0,
            dropped_count=0,
            closed_kinds={},
            dropped_reasons={},
            already_closed=True,
        )
    )


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def repair(events: Iterable[Event]) -> RepairedEventStream:
    """Reconstruct a coherent event stream from a possibly-truncated log.

    Deterministic + idempotent: ``repair(repair(x)) == repair(x)`` and
    two independent calls on the same input produce byte-identical
    ``Event`` values. See module docstring for the open->close mapping
    and the id-derivation formula.

    Contract:

    - Every input event is preserved in ``events`` (in input order).
      SP Q7 PARTIAL fold: the ``dropped_events`` list + drop-reason
      histogram are RESERVED API SURFACE for a future incoherence
      policy (e.g. flagging an isolated ``response.received`` with
      no preceding ``prompt.sent``). Today no drop rule fires, so
      ``dropped_events`` is always empty and ``already_closed`` on
      the summary reflects the no-synth path. The reader
      (``EventReader.iter_events``) handles byte-level tail
      truncation before events reach repair(); repair only sees
      valid Event objects.
    - Synthesized close events appear at the end of ``events`` in a
      deterministic order (sorted by open event's ``timestamp_ns``
      then by open event's id) so a second call reproduces the same
      sequence.
    - Chain integrity: synthesized events carry valid ``prev_hash``
      links extending the chain from the last input event.
    - Idempotence: a synthesized close on pass 1 is recognised as the
      close of its corresponding open on pass 2, so pass 2 adds no
      new closes and returns bytewise-identical ``events``.

    Args:
        events: the events to repair; typically the output of
            :meth:`ract.trace.writer.EventReader.iter_events` or an
            in-memory :class:`ract.trace.events.EventChain.events`.

    Returns:
        :class:`RepairedEventStream` with the repair summary + the
        full repaired sequence.
    """
    kept: list[Event] = []
    dropped: list[Event] = []
    dropped_reasons: dict[str, int] = {}
    # Open handles keyed by (open_kind, source_event_id_hex). The key
    # is the pair so two `tool.called` events (different ids) each
    # get their own open slot. When a close event arrives, we look
    # up the pair (paired_open_kind, close_payload["source_event_id"])
    # -- for a real close event, source_event_id is missing, so we
    # need a different match rule: real closes remove the OLDEST
    # matching open of the paired kind (FIFO within same run/step).
    #
    # Synthesized close events (payload["synthesized"] == True) carry
    # source_event_id which lets us match by-id precisely; this is
    # the property that makes repair() idempotent -- a second pass
    # sees the synthesized close and matches it to the specific open
    # it was synthesized for, not just any open of the same kind.
    open_by_kind: dict[str, list[Event]] = {kind: [] for kind in _CLOSE_MAP}
    # Also track synthesized-close acknowledgements: if an event has
    # payload["synthesized"] == True and payload["source_event_id"]
    # matches an open we're tracking, remove the specific open.
    for ev in events:
        kept.append(ev)
        # If this event OPENS a handle, register it.
        if ev.kind in _CLOSE_MAP:
            open_by_kind[ev.kind].append(ev)
            continue
        # If this event CLOSES a handle, remove one matching open.
        if ev.kind in _CLOSE_KINDS:
            paired_open_kind = _CLOSE_KINDS[ev.kind]
            source_id_hex = ev.payload.get("source_event_id") if isinstance(ev.payload, dict) else None
            opens = open_by_kind.get(paired_open_kind, [])
            if source_id_hex is not None:
                # By-id match (idempotence path: this is a synthesized
                # close from a prior repair pass, pointing at a
                # specific open).
                for idx, cand in enumerate(opens):
                    if cand.id.hex() == source_id_hex:
                        opens.pop(idx)
                        break
            elif opens:
                # FIFO match: real closes pair with the earliest open
                # of their paired kind still unclosed.
                opens.pop(0)
    # Synthesize a close event for every still-open handle.
    # Determinism: sort by (timestamp_ns, id.hex()) so the append
    # order is stable across runs and Python versions.
    still_open: list[Event] = []
    for kind, opens in open_by_kind.items():
        still_open.extend(opens)
    still_open.sort(key=lambda e: (e.timestamp_ns, e.id.hex()))

    # Build synthesized close events chaining from the tip of the
    # kept events. We reuse EventChain solely for the tip_hash walk;
    # we do NOT invoke .append on the input events (they already
    # carry their own valid hashes and chain state).
    tip_hash = kept[-1].hash if kept else b"\x00" * 32
    # We also need a run_id for the synthesized events. If we have
    # any input events, use the first's run_id. If we have zero
    # input events, there are no opens either (already_closed=True)
    # and this branch is unreachable.
    run_id = kept[0].run_id if kept else b"\x00" * 16

    synthesized: list[Event] = []
    closed_kinds: dict[str, int] = {}
    for open_event in still_open:
        close_kind, close_payload_template = _CLOSE_MAP[open_event.kind]
        payload: dict[str, Any] = {
            **close_payload_template,
            "synthesized": True,
            "reason": "interrupted",
            "source_event_id": open_event.id.hex(),
        }
        synth_id = _derive_synth_id(open_event.id, close_kind)
        synth_ts = open_event.timestamp_ns + 1
        # Preserve step_id + parent_id lineage from the open event.
        step_id = open_event.step_id
        parent_id = open_event.parent_id
        h = hash_event(
            kind=close_kind,
            payload=payload,
            prev_hash=tip_hash,
            id_bytes=synth_id,
            run_id=run_id,
            step_id=step_id,
            parent_id=parent_id,
            timestamp_ns=synth_ts,
        )
        close_event = Event(
            id=synth_id,
            run_id=run_id,
            step_id=step_id,
            parent_id=parent_id,
            timestamp_ns=synth_ts,
            kind=close_kind,  # type: ignore[arg-type]
            payload=payload,
            hash=h,
            prev_hash=tip_hash,
        )
        synthesized.append(close_event)
        tip_hash = h
        closed_kinds[open_event.kind] = closed_kinds.get(open_event.kind, 0) + 1

    summary = RepairSummary(
        synthesized_count=len(synthesized),
        dropped_count=len(dropped),
        closed_kinds=closed_kinds,
        dropped_reasons=dropped_reasons,
        already_closed=(len(synthesized) == 0 and len(dropped) == 0),
    )

    if synthesized:
        _LOG.info(
            "repair: synthesized %d close event(s) for open handles: %s",
            len(synthesized),
            closed_kinds,
        )

    return RepairedEventStream(
        events=kept + synthesized,
        synthesized_close_events=synthesized,
        dropped_events=dropped,
        repair_summary=summary,
    )


def _derive_synth_id(open_event_id: bytes, close_kind: str) -> bytes:
    """Deterministic synthesized-event id from the open's id + close kind.

    Truncated sha256 gives 128 bits, matching real 16-byte UUIDs; the
    id derivation is stable across CPython versions and platforms.
    """
    h = hashlib.sha256()
    h.update(_SYNTH_MARKER)
    h.update(open_event_id)
    h.update(close_kind.encode("utf-8"))
    return h.digest()[:16]


# ---------------------------------------------------------------------------
# Chain reconstruction convenience
# ---------------------------------------------------------------------------


def rebuild_chain_from_repaired(stream: RepairedEventStream) -> EventChain:
    """Rebuild an :class:`EventChain` from a repaired stream.

    Useful for tests + tools that want to inspect the tip_hash + walk
    the chain after repair. The chain is re-validated on ``append`` so
    a synthesized event with a corrupt hash surfaces as
    :class:`ChainBrokenError` here.
    """
    if not stream.events:
        # No events -> no chain. Caller decides how to handle.
        raise ValueError("cannot rebuild chain from empty repaired stream")
    chain = EventChain(run_id=stream.events[0].run_id)
    for event in stream.events:
        chain.append(event)
    return chain


__all__ = [
    "RepairSummary",
    "RepairedEventStream",
    "rebuild_chain_from_repaired",
    "repair",
]


# RACT 0.5.1
