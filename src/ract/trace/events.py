"""Event + EventKind + hash-chained EventChain.

SUBSTRATE §6.3 defines the closed vocabulary; this module is the closed
set in code. Every event carries a SHA-256 of its canonical JSON payload
and a ``prev_hash`` reference to the tip hash at append time — that is
the "hash chain" the operator ships with a run.

Reference sources:

- SUBSTRATE §6 (The Trace is the Product).
- OpenTelemetry Python API/SDK repository:
  ``https://github.com/open-telemetry/opentelemetry-python`` — the
  ``payload`` field maps to span attributes under the ``ract.*``
  namespace (see ``ract.trace.otel``).
- OpenTelemetry GenAI Semantic Conventions SIG:
  ``https://github.com/open-telemetry/semantic-conventions`` — the
  event kinds match the conventions' multi-agent vocabulary (tasks,
  actions, memory, agent teams, artifact tracking).
- Temporal durable-execution model: ``https://docs.temporal.io/`` — the
  workflow-history-as-source-of-truth pattern that motivates the
  reporter-as-projection migration.
- OpenHands SDK: ``https://github.com/All-Hands-AI/OpenHands`` — the
  per-iteration tracing pattern (tool-call I/O capture, LLM API
  request spans, conversation lifecycle).
- JSON Schema Draft 2020-12: ``https://json-schema.org/`` — the
  canonical form the ``payload`` field serialises into.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from ract.canonical import dumps_jcs


# ---------------------------------------------------------------------------
# Closed EventKind vocabulary
# ---------------------------------------------------------------------------


# SUBSTRATE §6.3 lists these; the set is closed at the type level. Adding
# a kind is an explicit schema-version bump in ``docs/EVENTS.md``.
EventKind = Literal[
    # Run-level
    "run.started",
    "run.completed",
    "run.aborted",
    # Step transactions (module_02)
    "step.started",
    "step.committed",
    "step.rolled_back",
    # Provider I/O (module_04)
    "prompt.sent",
    "response.received",
    "response.validated",
    "response.rejected",
    # Tool dispatch
    "tool.called",
    "tool.result",
    "tool.refused",
    # Sandbox (module_03)
    "sandbox.granted",
    "sandbox.denied",
    "sandbox.unenforced",
    # v0.5.1 wiring module_04 (Lens C C-02 + C-10 closure): every
    # sandbox backend (Linux bwrap, macOS Seatbelt, Windows stub)
    # emits this event on entry with the env-allowlist audit. Payload
    # carries ``backend``, ``allowlist_source`` (manifest/file/default),
    # ``scrubbed_count`` (env vars stripped from the child), and
    # ``never_passthrough_denied`` (allowlist entries refused by the
    # NEVER_PASSTHROUGH deny surface). The event turns credential-
    # exfil defense from silent WARN-log into a first-class trace
    # signal an auditor can correlate to a specific run/step.
    "sandbox.env_scrubbed",
    # Predicates (module_01)
    "predicate.evaluated",
    # Handshakes
    "handshake.requested",
    "handshake.resolved",
    # Rootknot / provenance
    "rootknot.created",
    "rootknot.verified",
    # Assumptions
    "assumption.proposed",
    "assumption.accepted",
    "assumption.discharged",
    "assumption.violated",
    # Contracts (module_06 — Auction as scheduled environment sweep)
    "auction.proposal",
    # ALM module_01 (visible-holdout gap, mutation-kill below threshold)
    "laziness.violated",
    # ALM module_05 (sycophancy circuit + Investigator pre-completion contract)
    "reversal.suspicious",
    "investigator.report",
    # Plan mutation + pre-execution advisory (cluster 2 findings 4 + 3)
    "plan.rewritten",
    "plan.risk_assessed",
    # v0.5.0 memory discipline (module_09 §Signals items 11-13).
    # Seven new kinds bump the closed vocabulary. Producers live in
    # ``src/ract/memory/events.py`` (mirror-string constants there);
    # this Literal is the load-bearing gate that closes at write time.
    "budget.declared",
    "budget.exceeded",
    "retrieval.requested",
    "retrieval.satisfied",
    "retrieval.cascaded",
    "retrieval.refused",
    "probe.evaluated",
    # v0.5.1 module_07 (Historical Manifest Ledger, RK-3 durability).
    # Emitted every time :class:`ract.security.manifest_ledger.ManifestLedger`
    # successfully appends a new observation of an RK-3 environment
    # attestation. Payload carries the ledger entry index, the
    # manifest_digest observed, the prev_ledger_hash the entry
    # references, and the number of tool ids invoked at ledger-append
    # time. See ``_BUILD/ract_v0.5.1_external_review_response/module_07.md``.
    "manifest.ledger.appended",
    # v0.5.1 module_07 SP Q5 amendment: signals a ledger observer that
    # was BOUND (ambient ledger available) but failed to append -- disk
    # full, permission change, lock contention, or malformed payload.
    # Downstream ``ract verify`` uses this event to distinguish
    # "ledger was never bound" (no event) from "ledger was bound but
    # refused" (this event). Payload carries the manifest_digest, the
    # run_id, and an error_kind string.
    "manifest.ledger.refused",
    # v0.5.1 module_09 (Sycophancy classifier upgrade -- AST-delta +
    # WhispererContract-event). Emitted by
    # :meth:`ract.antilazy.sycophancy_v2.SycophancyClassification.emit_event`
    # when the response's structural commitment count is below
    # ``MIN_COMMITMENT_FLOOR`` (default 3). Payload carries
    # commitment_count, floor, response_excerpt_hash (16-hex prefix of
    # sha256 over the first 256 bytes of the response), run_id (ambient
    # or empty), null_op_score, and used_regex_fallback. This event
    # signals that a whisperer contract turn returned an empty
    # commitment surface -- the operator or a downstream gate can
    # decide whether to reject the turn, force a re-ask, or record the
    # violation for post-run audit.
    "whisperer.contract_violation",
    # v0.5.1 wiring module_05 (Lens C C-03 closure). Emitted by
    # :meth:`ract.executor.loop.SubstrateLoop._reap_active_processes`
    # once per handle killed. Payload carries ``pid``, ``argv0`` (the
    # command name; not the whole argv to bound log width), ``argv_len``,
    # ``reason`` (postcondition_failed / commit_failed /
    # run_step_exception / dispose_unsuccessful), and ``reap_latency_ms``
    # (monotonic delta from spawn to reap). The event turns the
    # process-group tree-kill from silent WARN into a first-class trace
    # signal an auditor can grep to reconstruct which descendant trees
    # a specific rollback path SIGKILL'd.
    "process.reaped",
    # v0.5.1 spec-completeness module_02 (Lens 1A CRITICAL A-2 closure).
    # Emitted by
    # :func:`ract.memory.functions.provider_adapter.seat_state_section`
    # when a state_context section is truncated to satisfy the master
    # spec's 15%-of-input_target sub-budget cap
    # (``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Context
    # Composition line 71). Payload carries ``function``,
    # ``cap_tokens`` (floor(0.15 * input_target)),
    # ``requested_tokens`` (pre-truncate seated size),
    # ``seated_tokens`` (post-truncate seated size),
    # ``dropped_entry_count`` (lines dropped by the truncation walk),
    # and ``strategy`` (``truncate_tail`` today; future strategies may
    # introduce ``drop_lowest_priority`` or ``summarize``).
    "state.budget_capped",
]


LEGAL_EVENT_KINDS: frozenset[str] = frozenset(get_args(EventKind))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChainBrokenError(RuntimeError):
    """Raised when ``EventChain.append`` sees a ``prev_hash`` mismatch.

    The mismatch means either (a) the appender computed the chain from a
    stale tip (a programming error) or (b) a middle event has been
    tampered with on disk (an integrity failure). ``EventReader.load``
    surfaces (b) explicitly at load time.
    """


# ---------------------------------------------------------------------------
# Canonical serialisation
# ---------------------------------------------------------------------------


# v0.5.1 module_03: canonical bytes are RFC 8785 JCS — stable across
# CPython minor versions, PyPy, and Windows/POSIX line endings.
def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Return the canonical JSON bytes of ``payload`` for hashing."""
    return dumps_jcs(payload)


def hash_event(
    kind: str,
    payload: dict[str, Any],
    prev_hash: bytes,
    *,
    id_bytes: bytes,
    run_id: bytes,
    step_id: bytes | None,
    parent_id: bytes | None,
    timestamp_ns: int,
) -> bytes:
    """Compute the SHA-256 chain hash for an event.

    The hash covers every load-bearing field. ``prev_hash`` extends the
    chain; a bit-flip anywhere in the middle of the log surfaces as a
    mismatch on load.
    """
    h = hashlib.sha256()
    h.update(kind.encode("utf-8"))
    h.update(b"\x00")
    h.update(id_bytes)
    h.update(run_id)
    h.update(step_id or b"\x00" * 16)
    h.update(parent_id or b"\x00" * 16)
    h.update(timestamp_ns.to_bytes(8, "big", signed=False))
    h.update(canonical_payload_bytes(payload))
    h.update(prev_hash)
    return h.digest()


# ---------------------------------------------------------------------------
# Event value
# ---------------------------------------------------------------------------


def new_event_id() -> bytes:
    """Return a fresh 16-byte event identifier."""
    return uuid.uuid4().bytes


@dataclass(frozen=True)
class Event:
    """One durable event.

    Field shapes:

    - ``id`` / ``run_id`` / ``step_id`` / ``parent_id`` are 16-byte
      UUIDs; the two nullable fields are ``None`` for run-level or
      root-caused events respectively.
    - ``payload`` is a JSON-serialisable dict; per-kind schemas live in
      ``docs/EVENTS.md``.
    - ``hash`` and ``prev_hash`` are 32-byte SHA-256 digests.

    The value is frozen so an event cannot be mutated after append.
    """

    id: bytes
    run_id: bytes
    step_id: bytes | None
    parent_id: bytes | None
    timestamp_ns: int
    kind: EventKind
    payload: dict[str, Any]
    hash: bytes
    prev_hash: bytes

    def __post_init__(self) -> None:
        if len(self.id) != 16:
            raise ValueError("event id must be 16 bytes")
        if len(self.run_id) != 16:
            raise ValueError("run_id must be 16 bytes")
        if self.step_id is not None and len(self.step_id) != 16:
            raise ValueError("step_id must be 16 bytes or None")
        if self.parent_id is not None and len(self.parent_id) != 16:
            raise ValueError("parent_id must be 16 bytes or None")
        if self.kind not in LEGAL_EVENT_KINDS:
            raise ValueError(
                f"unknown event kind {self.kind!r}; "
                f"legal kinds: {sorted(LEGAL_EVENT_KINDS)}"
            )
        if len(self.hash) != 32:
            raise ValueError("hash must be 32 bytes (SHA-256)")
        if len(self.prev_hash) != 32:
            raise ValueError("prev_hash must be 32 bytes (SHA-256)")

    def to_canonical_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict form (hex-encoded byte fields)."""
        return {
            "id": self.id.hex(),
            "run_id": self.run_id.hex(),
            "step_id": self.step_id.hex() if self.step_id is not None else None,
            "parent_id": (self.parent_id.hex() if self.parent_id is not None else None),
            "timestamp_ns": self.timestamp_ns,
            "kind": self.kind,
            "payload": self.payload,
            "hash": self.hash.hex(),
            "prev_hash": self.prev_hash.hex(),
        }

    @classmethod
    def from_canonical_dict(cls, raw: dict[str, Any]) -> "Event":
        """Rebuild an ``Event`` from the on-disk canonical form."""
        return cls(
            id=bytes.fromhex(raw["id"]),
            run_id=bytes.fromhex(raw["run_id"]),
            step_id=(bytes.fromhex(raw["step_id"]) if raw.get("step_id") else None),
            parent_id=(
                bytes.fromhex(raw["parent_id"]) if raw.get("parent_id") else None
            ),
            timestamp_ns=int(raw["timestamp_ns"]),
            kind=raw["kind"],
            payload=dict(raw["payload"]),
            hash=bytes.fromhex(raw["hash"]),
            prev_hash=bytes.fromhex(raw["prev_hash"]),
        )


# ---------------------------------------------------------------------------
# EventChain
# ---------------------------------------------------------------------------


# The genesis prev_hash is 32 zero bytes; the tip of an empty chain is
# the same value. This gives ``EventReader.load`` a well-defined check
# for the first line of the log.
_GENESIS_HASH: bytes = b"\x00" * 32


@dataclass
class EventChain:
    """Append-only in-memory chain of ``Event`` values.

    ``append`` refuses mismatched ``prev_hash``; ``build_next`` is the
    convenience factory the emit sites call.
    """

    run_id: bytes
    events: list[Event] = field(default_factory=list)
    tip_hash: bytes = _GENESIS_HASH

    def append(self, event: Event) -> None:
        """Validate the chain link and append."""
        if event.prev_hash != self.tip_hash:
            raise ChainBrokenError(
                "prev_hash mismatch: expected "
                f"{self.tip_hash.hex()}, got {event.prev_hash.hex()}"
            )
        # Re-hash the event to catch a tampered payload before it lands.
        expected = hash_event(
            kind=event.kind,
            payload=event.payload,
            prev_hash=event.prev_hash,
            id_bytes=event.id,
            run_id=event.run_id,
            step_id=event.step_id,
            parent_id=event.parent_id,
            timestamp_ns=event.timestamp_ns,
        )
        if expected != event.hash:
            raise ChainBrokenError(
                "hash mismatch: recomputed hash does not match declared hash"
            )
        self.events.append(event)
        self.tip_hash = event.hash

    def build_next(
        self,
        *,
        kind: EventKind,
        payload: dict[str, Any],
        step_id: bytes | None = None,
        parent_id: bytes | None = None,
        timestamp_ns: int | None = None,
    ) -> Event:
        """Build the next ``Event`` linked to the current tip.

        Does not append; the caller (typically a ``JsonlEventWriter``)
        writes the event to disk and then calls ``append``.
        """
        ts = timestamp_ns if timestamp_ns is not None else time.time_ns()
        eid = new_event_id()
        h = hash_event(
            kind=kind,
            payload=payload,
            prev_hash=self.tip_hash,
            id_bytes=eid,
            run_id=self.run_id,
            step_id=step_id,
            parent_id=parent_id,
            timestamp_ns=ts,
        )
        return Event(
            id=eid,
            run_id=self.run_id,
            step_id=step_id,
            parent_id=parent_id,
            timestamp_ns=ts,
            kind=kind,
            payload=payload,
            hash=h,
            prev_hash=self.tip_hash,
        )


__all__ = [
    "ChainBrokenError",
    "Event",
    "EventChain",
    "EventKind",
    "LEGAL_EVENT_KINDS",
    "canonical_payload_bytes",
    "hash_event",
    "new_event_id",
]


# RACT 0.4.0
