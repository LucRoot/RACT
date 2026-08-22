"""Trace-log verify result + incremental verify sidecar.

v0.5.2 hardening module_05 (DA-B F-4.1/F-4.2/F-4.4/F-4.5/F-4.6).

Two responsibilities:

1. :class:`TraceVerifyResult` -- the single frozen dataclass every
   trace-log verify entry point returns. Callers switch on
   ``.status`` (a closed :data:`TraceVerifyStatus` literal) rather
   than probing dict shapes. Structural errors (missing file,
   permission denied) still raise -- content-level failures
   surface as dataclass statuses.

2. :func:`incremental_verify` + :func:`cold_verify` -- warm verify
   reads a per-run sidecar at
   ``.ract/trace/{run_id}.verify.json``, seeks to
   ``last_verified_offset``, replays only the delta, and updates
   the sidecar atomically at end. Cold verify (no sidecar OR
   sidecar refused) re-reads the whole file.

TRUST MODEL (Fork 1 verdict + docstring per Ox Alpha co-build):
the verify sidecar sits on the same filesystem as the trace log.
An attacker with write access to ``events.jsonl`` also has write
access to the sidecar and can forge a ``verified_head`` that
advances past the tampered region. **The verify sidecar is a
PERFORMANCE primitive, not a security boundary.** Tamper defense
lives in ``manifest_ledger`` external anchoring (v0.6 backlog).
Operators who suspect tamper pass ``force_cold=True`` (CLI
``ract trace verify --cold``) to bypass the sidecar and re-verify
from GENESIS.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from ract.trace.events import (
    ChainBrokenError,
    Event,
    EventChain,
    LEGAL_EVENT_KINDS,
    _GENESIS_HASH,
    hash_event,
)


_LOG = logging.getLogger("ract.trace.verify")


# ---------------------------------------------------------------------------
# Status literal + dataclass
# ---------------------------------------------------------------------------


TraceVerifyStatus = Literal[
    "VALID",
    "INVALID",
    "TORN_TAIL",
    "TAMPERED",
]
"""Closed status vocabulary for :class:`TraceVerifyResult`.

Per Ox Alpha co-build Fork 3 verdict (b): four statuses ship in
v0.5.2. A future ``PARTIAL`` status is RESERVED for the external-
anchor feature (v0.6+ backlog) that carries an ``expected_count``
capable of detecting explicit truncation; without an anchor,
truncation is indistinguishable from a legitimate short run and
shipping the status now would leave a dead branch.

- ``VALID`` -- every event verified; chain terminates cleanly.
- ``INVALID`` -- structural refusal recoverable as a dataclass.
  Reachable from: (a) OSError reading the trace file (permission
  denied, disk error) surfaced as a dataclass instead of a raise
  so any caller can uniformly switch on ``.status``; (b) sidecar
  header schema/type refused when strict warm-path was demanded.
- ``TORN_TAIL`` -- last-line torn-write recovered: chain
  terminates cleanly at the last verified event. Callers asking
  "can I resume?" check :attr:`is_valid` (True for VALID +
  TORN_TAIL); callers asking "is this trace pristine?" check
  :attr:`is_healthy` (True only for VALID).
- ``TAMPERED`` -- middle-event hash mismatch OR mutated payload.
  ``tamper_details`` names the offending offset + event index.

**Reserved (v0.6+):** ``PARTIAL`` -- external anchor detected
fewer events on disk than expected. NOT part of the current
Literal to keep the accept surface tight; will be added in the
same schema-version bump that introduces the anchor.
"""

_LEGAL_STATUSES: frozenset[str] = frozenset(
    ("VALID", "INVALID", "TORN_TAIL", "TAMPERED")
)


@dataclass(frozen=True)
class TraceVerifyResult:
    """The one shape every trace-log verify entry point returns.

    Fields:

    - ``status`` -- :data:`TraceVerifyStatus` literal.
    - ``verified_head`` -- last known-good chain tip hex, or
      ``None`` for an empty file / cold start with no events.
    - ``verified_offset`` -- byte offset up to which the chain
      verified. On VALID this equals the file size; on
      TORN_TAIL this equals the end of the last complete line;
      on TAMPERED this equals the start of the first bad line.
    - ``events_verified`` -- count of complete events whose
      hashes checked out.
    - ``events_torn`` -- 0 or 1; a torn-tail file contributes 1.
    - ``events_tampered`` -- count of middle-event tamper hits
      (usually 1 -- verify halts on the first).
    - ``reason`` -- human-readable single sentence for the CLI.
    - ``tamper_details`` -- populated iff ``status == "TAMPERED"``
      with ``{offset, event_index, kind, expected_prev_hash,
      claimed_prev_hash, computed_hash, claimed_hash}``.

    Structural errors (FileNotFoundError, PermissionError, real
    OS refusals) still raise. Any callers who prefer a total
    surface can catch + build an ``.invalid(reason=str(exc))``
    dataclass at the boundary.
    """

    status: TraceVerifyStatus
    verified_head: str | None
    verified_offset: int
    events_verified: int
    events_torn: int
    events_tampered: int
    reason: str
    tamper_details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Structural invariant: status must be in the closed set.
        if self.status not in _LEGAL_STATUSES:
            raise ValueError(
                f"TraceVerifyResult.status must be one of "
                f"{sorted(_LEGAL_STATUSES)}; got {self.status!r}"
            )
        if self.events_torn not in (0, 1):
            raise ValueError(
                f"TraceVerifyResult.events_torn must be 0 or 1; "
                f"got {self.events_torn!r}"
            )
        if self.verified_offset < 0:
            raise ValueError(
                f"TraceVerifyResult.verified_offset must be >= 0; "
                f"got {self.verified_offset!r}"
            )
        # tamper_details required iff status == TAMPERED.
        if self.status == "TAMPERED" and not self.tamper_details:
            raise ValueError(
                "TraceVerifyResult.tamper_details is required when status == 'TAMPERED'"
            )
        if self.status != "TAMPERED" and self.tamper_details is not None:
            raise ValueError(
                f"TraceVerifyResult.tamper_details must be None when "
                f"status != 'TAMPERED'; got {self.tamper_details!r} "
                f"for status={self.status!r}"
            )

    @property
    def is_valid(self) -> bool:
        """True when the operator can safely resume from this trace.

        VALID + TORN_TAIL both return True -- a torn tail is a
        clean crash recovery, not a security failure. TAMPERED,
        INVALID, PARTIAL return False.
        """
        return self.status in ("VALID", "TORN_TAIL")

    @property
    def is_healthy(self) -> bool:
        """True only when the chain is pristine (VALID).

        Callers who want "no crash recovery, no tamper, nothing
        weird" check this. TORN_TAIL fails this check even though
        :attr:`is_valid` succeeds.
        """
        return self.status == "VALID"

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def valid(
        cls,
        *,
        verified_head: str | None,
        verified_offset: int,
        events_verified: int,
        reason: str = "chain intact",
    ) -> "TraceVerifyResult":
        """Construct a VALID result."""
        return cls(
            status="VALID",
            verified_head=verified_head,
            verified_offset=verified_offset,
            events_verified=events_verified,
            events_torn=0,
            events_tampered=0,
            reason=reason,
            tamper_details=None,
        )

    @classmethod
    def torn_tail(
        cls,
        *,
        verified_head: str | None,
        verified_offset: int,
        events_verified: int,
        reason: str = "torn tail recovered; chain terminates at last complete event",
    ) -> "TraceVerifyResult":
        """Construct a TORN_TAIL result."""
        return cls(
            status="TORN_TAIL",
            verified_head=verified_head,
            verified_offset=verified_offset,
            events_verified=events_verified,
            events_torn=1,
            events_tampered=0,
            reason=reason,
            tamper_details=None,
        )

    @classmethod
    def tampered(
        cls,
        *,
        verified_head: str | None,
        verified_offset: int,
        events_verified: int,
        tamper_details: dict[str, Any],
        reason: str = "middle-event hash mismatch",
    ) -> "TraceVerifyResult":
        """Construct a TAMPERED result. ``tamper_details`` is required."""
        if not tamper_details:
            raise ValueError(
                "TraceVerifyResult.tampered() requires non-empty tamper_details"
            )
        return cls(
            status="TAMPERED",
            verified_head=verified_head,
            verified_offset=verified_offset,
            events_verified=events_verified,
            events_torn=0,
            events_tampered=1,
            reason=reason,
            tamper_details=dict(tamper_details),
        )

    @classmethod
    def invalid(
        cls,
        *,
        reason: str,
        verified_head: str | None = None,
        verified_offset: int = 0,
        events_verified: int = 0,
    ) -> "TraceVerifyResult":
        """Construct an INVALID result (recoverable structural refusal).

        For future header-mismatch or sidecar-shape refusals we
        prefer to surface as a dataclass. Currently unreachable
        in v0.5.2 code paths; kept for wire-format completeness.
        """
        return cls(
            status="INVALID",
            verified_head=verified_head,
            verified_offset=verified_offset,
            events_verified=events_verified,
            events_torn=0,
            events_tampered=0,
            reason=reason,
            tamper_details=None,
        )


# ---------------------------------------------------------------------------
# Verify-sidecar wiring (reuses module_04 sidecar_header primitive)
# ---------------------------------------------------------------------------


TRACE_VERIFY_SIDECAR_TYPE = "trace_verify"
TRACE_VERIFY_SIDECAR_SCHEMA = 1


def _ensure_trace_verify_sidecar_type_registered() -> None:
    """Idempotently register the ``trace_verify`` sidecar_type.

    module_04's :mod:`ract.sidecar_header` registers
    ``loop_state`` at import; ``trace_verify`` is new in module_05
    and registers on first use. Repeated registration with the
    same version set is a strict overwrite (no-op semantically).
    """
    from ract import sidecar_header as _sh

    snap = _sh.snapshot_registry()
    if TRACE_VERIFY_SIDECAR_TYPE not in snap:
        _sh.register_sidecar_type(
            TRACE_VERIFY_SIDECAR_TYPE,
            frozenset({TRACE_VERIFY_SIDECAR_SCHEMA}),
        )


def _sidecar_path_for(events_path: Path, run_id_hex: str) -> Path:
    """Return the canonical sidecar path for a given events log.

    Convention: hermetic per-run. Sidecar lives in the SAME
    directory as the events log, named
    ``{run_id_hex}.verify.json``. RACT places events at
    ``<runs_root>/<run_id>/events.jsonl`` so the sidecar lands at
    ``<runs_root>/<run_id>/{run_id}.verify.json`` -- an operator
    inspecting a run directory sees both artifacts side by side,
    and a test-generated events file in ``/tmp/foo/events.jsonl``
    gets its sidecar at ``/tmp/foo/{run_id}.verify.json`` (no
    accidental pollution of ``~/.ract`` or any other global
    location). Callers that want an explicit path pass
    ``sidecar_path=`` directly.
    """
    return events_path.resolve().parent / f"{run_id_hex}.verify.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_verify_sidecar(
    *,
    sidecar_path: Path,
    run_id_hex: str,
    verified_head: str | None,
    verified_offset: int,
    events_verified: int,
) -> None:
    """Persist the warm-verify checkpoint (tmp+rename atomic)."""
    _ensure_trace_verify_sidecar_type_registered()
    from ract.sidecar_header import write_json_sidecar_with_header

    body = {
        "last_verified_head": verified_head,
        "last_verified_offset": int(verified_offset),
        "last_verified_events": int(events_verified),
        "last_verified_at": _now_iso(),
    }
    write_json_sidecar_with_header(
        sidecar_path,
        body=body,
        sidecar_type=TRACE_VERIFY_SIDECAR_TYPE,
        schema_version=TRACE_VERIFY_SIDECAR_SCHEMA,
        run_id=run_id_hex,
    )


def _read_verify_sidecar(
    *,
    sidecar_path: Path,
    expected_run_id_hex: str,
) -> dict[str, Any] | None:
    """Read + validate the sidecar; return the body dict or None.

    Returns None (and logs a WARN) on any of:
    - sidecar path missing / empty (cold start)
    - header missing / run_id mismatch / schema mismatch
    - body shape invalid
    Never raises for cache-miss reasons -- the caller falls back
    to cold verify. Only real OS refusals (PermissionError) raise.
    """
    if not sidecar_path.is_file():
        return None
    _ensure_trace_verify_sidecar_type_registered()
    from ract.sidecar_header import (
        SidecarHeaderError,
        read_sidecar_header,
    )

    try:
        header = read_sidecar_header(
            sidecar_path,
            sidecar_type=TRACE_VERIFY_SIDECAR_TYPE,
            expected_run_id=expected_run_id_hex,
            strict=True,
        )
    except SidecarHeaderError as exc:
        _LOG.warning(
            "trace verify sidecar %s refused (%s); falling back to cold verify",
            sidecar_path,
            exc,
        )
        return None
    # Read the whole file to get the body under the header envelope.
    try:
        raw = sidecar_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning(
            "trace verify sidecar %s body unreadable (%s); cold-verify fallback",
            sidecar_path,
            exc,
        )
        return None
    if not isinstance(payload, dict):
        _LOG.warning(
            "trace verify sidecar %s body is not a dict; cold-verify fallback",
            sidecar_path,
        )
        return None
    # Strip the header envelope; body fields sit at top level per
    # json_body_with_header (module_04).
    body_keys = (
        "last_verified_head",
        "last_verified_offset",
        "last_verified_events",
        "last_verified_at",
    )
    body: dict[str, Any] = {}
    for k in body_keys:
        if k not in payload:
            _LOG.warning(
                "trace verify sidecar %s missing body field %r; cold-verify fallback",
                sidecar_path,
                k,
            )
            return None
        body[k] = payload[k]
    # SP amendment (Ox Alpha A Q3 DEFECT): strict type + bounds
    # check. `bool` is a subclass of `int` in Python
    # (isinstance(True, int) is True) -- an attacker writing
    # ``true`` for last_verified_offset would previously satisfy
    # the int check + become seek(1). Now excluded via
    # ``not isinstance(x, bool)``. Also reject negative offsets +
    # negative events counts: previously a crafted sidecar with
    # offset=-1 satisfied the int check, propagated to
    # fp.seek(-1), and raised OSError -- breaking the module's
    # "Never raises for cache-miss reasons" contract in
    # ``_read_verify_sidecar``. Reject in the reader so a bad
    # sidecar cleanly cold-fallbacks.
    off = body["last_verified_offset"]
    if isinstance(off, bool) or not isinstance(off, int) or off < 0:
        _LOG.warning(
            "trace verify sidecar %s last_verified_offset must be non-negative int "
            "(not bool); got %r; cold-verify fallback",
            sidecar_path,
            off,
        )
        return None
    ev_count = body["last_verified_events"]
    if isinstance(ev_count, bool) or not isinstance(ev_count, int) or ev_count < 0:
        _LOG.warning(
            "trace verify sidecar %s last_verified_events must be non-negative int "
            "(not bool); got %r; cold-verify fallback",
            sidecar_path,
            ev_count,
        )
        return None
    head_val = body["last_verified_head"]
    if head_val is not None:
        if not isinstance(head_val, str):
            _LOG.warning(
                "trace verify sidecar %s last_verified_head must be str or None; "
                "cold-verify fallback",
                sidecar_path,
            )
            return None
        # SHA-256 hex is 64 chars. Reject other lengths cheaply so
        # a downstream bytes.fromhex(head_val) that would
        # otherwise raise ValueError falls back cleanly here.
        if len(head_val) != 64 or any(
            c not in "0123456789abcdefABCDEF" for c in head_val
        ):
            _LOG.warning(
                "trace verify sidecar %s last_verified_head must be 64-char hex; "
                "got len=%d; cold-verify fallback",
                sidecar_path,
                len(head_val),
            )
            return None
    del header  # currently unused past validation; retained for future audit
    return body


# ---------------------------------------------------------------------------
# Verify entry points
# ---------------------------------------------------------------------------


# Torn-tail sentinel emitted by EventReader.iter_events on the LAST line.
_TORN_TAIL_KEY = "__torn_tail__"


# Ox Alpha co-build Fork 1 (b): warm-mode near-tail spot-check.
# Before trusting the sidecar's verified_head, cold-verify the LAST
# N events. Catches the dominant tamper shape (edit near-tail + bump
# offset) at ~64 hash ops per warm verify -- noise against the O(n^2)
# we are fixing. Mid-file tamper is still uncatchable without an
# external anchor -- that gap is documented + belongs to
# manifest_ledger / receipt_chain (v0.6 backlog).
WARM_SPOT_CHECK_EVENTS: int = 64


def _iter_lines_with_offsets(
    events_path: Path,
    *,
    start_offset: int = 0,
) -> Iterator[tuple[int, str, bool]]:
    """Yield ``(end_offset, line_text, is_torn_tail)`` for each JSONL line.

    - ``end_offset`` is the byte offset AFTER the trailing newline
      (or file end for the final line without newline). Used to
      advance the sidecar's ``last_verified_offset``.
    - ``line_text`` is the decoded line content (no newline; no
      leading/trailing whitespace stripped -- the caller decides).
    - ``is_torn_tail`` is True only for the LAST line iff it (a)
      lacks a trailing newline AND (b) failed strict UTF-8
      decode; we retry the tail with ``errors="replace"`` so the
      caller can inspect the partial bytes as a repr and decide.

    Streaming: reads one line at a time via a raw file handle;
    never materializes the whole file. Universal-newlines mode
    (``newline=None``) collapses ``\r\n`` -> ``\n`` on both
    Windows- and POSIX-authored logs.

    Middle-line UTF-8 corruption is NOT retried with
    ``errors="replace"`` -- corruption outside the tail is a real
    :class:`ChainBrokenError` case and must surface loudly.
    """
    if not events_path.is_file():
        return
    file_size = events_path.stat().st_size
    if start_offset >= file_size:
        return
    # Open raw binary so we can measure real byte offsets AND
    # retry the tail line with errors="replace" without re-opening.
    with open(events_path, "rb") as fp:
        if start_offset > 0:
            fp.seek(start_offset)
        cur_offset = start_offset
        buf: list[bytes] = []
        while True:
            chunk = fp.readline()
            if not chunk:
                break
            end_offset = cur_offset + len(chunk)
            # Detect whether this is the last line by peeking.
            is_last = end_offset >= file_size
            # A well-terminated line ends in \n or \r\n.
            has_newline = chunk.endswith(b"\n")
            raw_line = chunk
            # Trim trailing newline(s) universally: strip \n then any \r.
            if raw_line.endswith(b"\r\n"):
                raw_line = raw_line[:-2]
            elif raw_line.endswith(b"\n"):
                raw_line = raw_line[:-1]
            # Torn tail: last line AND no terminating newline.
            torn_tail_flag = False
            try:
                text = raw_line.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                if is_last and not has_newline:
                    # Retry the tail with errors="replace" so the
                    # caller sees the partial bytes as a torn-tail
                    # sentinel + we do not crash.
                    text = raw_line.decode("utf-8", errors="replace")
                    torn_tail_flag = True
                else:
                    # Middle-line UTF-8 corruption. Do NOT retry;
                    # let the caller raise ChainBrokenError.
                    raise
            yield end_offset, text, torn_tail_flag
            cur_offset = end_offset
            # If we saw a torn tail we do not iterate further --
            # the file's remaining bytes are the partial line.
            if torn_tail_flag:
                return
        _ = buf  # unused; kept for future batched read


def _walk_verify(
    *,
    events_path: Path,
    chain: EventChain,
    start_offset: int,
    events_verified_prior: int,
) -> TraceVerifyResult:
    """Core verify walker: replay the file from ``start_offset``.

    ``chain`` is a fresh or partially-verified :class:`EventChain`
    -- for a cold verify the caller passes a chain with GENESIS
    ``tip_hash`` and no events; for a warm verify the caller
    seeds ``chain.tip_hash`` from the sidecar's ``verified_head``.
    """
    events_verified = events_verified_prior
    current_offset = start_offset
    tip_hex: str | None = (
        chain.tip_hash.hex()
        if events_verified_prior
        else (chain.tip_hash.hex() if chain.tip_hash != _GENESIS_HASH else None)
    )
    for end_offset, line_text, torn_tail in _iter_lines_with_offsets(
        events_path, start_offset=start_offset
    ):
        stripped = line_text.strip()
        if torn_tail:
            # Emit observability event + return TORN_TAIL. The
            # verifier stops here; the chain terminates cleanly
            # at ``current_offset`` (start of the torn line).
            _emit_torn_tail_event(events_path, current_offset, stripped)
            return TraceVerifyResult.torn_tail(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
            )
        if not stripped:
            current_offset = end_offset
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            # Matches v0.5.1 semantics + writer.py: ANY parse
            # failure on the LAST line in the file is torn-tail
            # tolerable (crash mid-write OR operator edit
            # corruption on tail). Middle-line json failures are
            # always TAMPERED.
            file_size = events_path.stat().st_size
            if end_offset >= file_size:
                _emit_torn_tail_event(events_path, current_offset, stripped[:120])
                return TraceVerifyResult.torn_tail(
                    verified_head=tip_hex,
                    verified_offset=current_offset,
                    events_verified=events_verified,
                )
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "json_decode_error",
                    "reason": str(exc),
                    "line_snippet": stripped[:200],
                },
                reason=(
                    f"malformed middle event line at offset {current_offset}: {exc}"
                ),
            )
        try:
            event = Event.from_canonical_dict(data)
        except (ValueError, KeyError, TypeError) as exc:
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "event_shape_invalid",
                    "reason": str(exc),
                    "line_snippet": stripped[:200],
                },
                reason=(f"malformed event shape at offset {current_offset}: {exc}"),
            )
        # Bind run_id lazily from the first event (cold start) so
        # we do not require the caller to know it up front.
        if not events_verified and chain.tip_hash == _GENESIS_HASH:
            chain = EventChain(run_id=event.run_id)
        # SP amendment (Ox Alpha A Q2 + cross-family Q2 DEFECT
        # CONVERGED): every event's run_id must match the chain's
        # bound run_id. Without this check an attacker splicing
        # an event from run B into run A's file passes prev_hash
        # + rehash (event.hash was computed by run B honestly)
        # and only the run_id would betray the splice. The
        # walker now surfaces the mismatch as TAMPERED with
        # kind="run_id_mismatch" so operators see the splice
        # class of tamper distinctly from payload tamper.
        if event.run_id != chain.run_id:
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "run_id_mismatch",
                    "expected_run_id": chain.run_id.hex(),
                    "claimed_run_id": event.run_id.hex(),
                },
                reason=(
                    f"run_id mismatch at offset {current_offset}: "
                    f"expected {chain.run_id.hex()[:12]}...; "
                    f"got {event.run_id.hex()[:12]}..."
                ),
            )
        # Kind must be legal (closed vocabulary).
        if event.kind not in LEGAL_EVENT_KINDS:
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "unknown_event_kind",
                    "event_kind": event.kind,
                },
                reason=f"unknown event kind {event.kind!r} at offset {current_offset}",
            )
        # prev_hash must match current tip.
        if event.prev_hash != chain.tip_hash:
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "prev_hash_mismatch",
                    "expected_prev_hash": chain.tip_hash.hex(),
                    "claimed_prev_hash": event.prev_hash.hex(),
                },
                reason=(
                    f"prev_hash mismatch at offset {current_offset}: "
                    f"expected {chain.tip_hash.hex()[:12]}...; "
                    f"got {event.prev_hash.hex()[:12]}..."
                ),
            )
        # Rehash payload and compare to claimed hash.
        recomputed = hash_event(
            kind=event.kind,
            payload=event.payload,
            prev_hash=event.prev_hash,
            id_bytes=event.id,
            run_id=event.run_id,
            step_id=event.step_id,
            parent_id=event.parent_id,
            timestamp_ns=event.timestamp_ns,
        )
        if recomputed != event.hash:
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "payload_tampered",
                    "computed_hash": recomputed.hex(),
                    "claimed_hash": event.hash.hex(),
                },
                reason=(
                    f"payload tamper at offset {current_offset}: "
                    f"computed {recomputed.hex()[:12]}... vs "
                    f"claimed {event.hash.hex()[:12]}..."
                ),
            )
        try:
            chain.append(event)
        except ChainBrokenError as exc:
            # Belt-and-suspenders: we already validated prev_hash
            # + rehash above; a ChainBrokenError here means the
            # dataclass round-trip surfaced something subtle we
            # missed. Report as TAMPERED with the raw reason.
            return TraceVerifyResult.tampered(
                verified_head=tip_hex,
                verified_offset=current_offset,
                events_verified=events_verified,
                tamper_details={
                    "offset": current_offset,
                    "event_index": events_verified,
                    "kind": "chain_broken",
                    "reason": str(exc),
                },
                reason=f"chain broken at offset {current_offset}: {exc}",
            )
        events_verified += 1
        tip_hex = event.hash.hex()
        current_offset = end_offset
    return TraceVerifyResult.valid(
        verified_head=tip_hex,
        verified_offset=current_offset,
        events_verified=events_verified,
    )


def cold_verify(events_path: Path | str) -> TraceVerifyResult:
    """Verify from GENESIS; ignore any warm sidecar.

    Callers pass ``force_cold=True`` to :func:`verify_trace` OR
    use this directly for a paranoid audit. On success the caller
    typically writes a fresh sidecar via
    :func:`persist_verify_sidecar`.

    A file that does NOT exist returns VALID (empty state -- new
    run before first emit). A file that exists but cannot be
    read (permission, disk error) returns INVALID with the
    OSError message -- callers switching on ``.status`` handle
    this uniformly instead of catching an exception.
    """
    p = Path(events_path)
    if not p.is_file():
        return TraceVerifyResult.valid(
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            reason=f"trace file {p} does not exist (nothing to verify)",
        )
    try:
        _ = p.stat()
    except OSError as exc:
        return TraceVerifyResult.invalid(
            reason=f"trace file {p} unreadable: {exc}",
        )
    # Start with a genesis chain; the first event's run_id seeds
    # the chain's run_id in _walk_verify.
    chain = EventChain(run_id=b"\x00" * 16)
    try:
        result = _walk_verify(
            events_path=p,
            chain=chain,
            start_offset=0,
            events_verified_prior=0,
        )
    except OSError as exc:
        # Read error partway through iteration -- return INVALID
        # so callers can uniformly switch on status.
        return TraceVerifyResult.invalid(
            reason=f"trace file {p} unreadable during iteration: {exc}",
        )
    except UnicodeDecodeError as exc:
        # SP amendment (Ox Alpha A Q4 DEFECT): middle-line UTF-8
        # corruption previously escaped cold_verify as a raw
        # UnicodeDecodeError -- violating the module's contract
        # that content-level failures surface as dataclass
        # statuses. Now it lands as TAMPERED with a diagnostic
        # tamper_details block so callers switch on .status
        # uniformly.
        return TraceVerifyResult.tampered(
            verified_head=None,
            verified_offset=int(getattr(exc, "start", 0) or 0),
            events_verified=0,
            tamper_details={
                "offset": int(getattr(exc, "start", 0) or 0),
                "event_index": 0,
                "kind": "middle_utf8_corruption",
                "reason": str(exc),
            },
            reason=f"middle-line UTF-8 corruption in {p}: {exc}",
        )
    except ChainBrokenError as exc:
        # Same rationale as UnicodeDecodeError -- surface as
        # TAMPERED for uniform caller handling.
        return TraceVerifyResult.tampered(
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            tamper_details={
                "offset": 0,
                "event_index": 0,
                "kind": "chain_broken",
                "reason": str(exc),
            },
            reason=f"chain broken in {p}: {exc}",
        )
    _emit_verify_completed_event(
        run_id=chain.run_id.hex() if chain.run_id != b"\x00" * 16 else None,
        result=result,
        mode="cold",
    )
    return result


def _read_events_in_range(
    events_path: Path, *, start_offset: int, end_offset: int
) -> tuple[list[tuple[int, Event]], bool, bool]:
    """Parse complete events whose byte ranges fall in [start, end].

    Returns ``(events_with_end_offsets, hit_torn_tail, complete)``.
    ``complete`` is True when iteration exited naturally (end of
    range reached OR torn tail encountered); False when iteration
    was cut short by a middle-line parse failure (json / shape /
    UTF-8 error) inside the window. The caller treats
    ``complete=False`` as "spot-check inconclusive" -> refuses to
    trust the sidecar -> falls back to cold verify.

    SP amendment (Ox Alpha A Q1 adjacent DEFECT): pre-amendment
    this was a 2-tuple returning ``(out, False)`` on parse
    failures -- silently truncating the checked prefix. An
    attacker could inject a garbage line WITHIN the tail window
    (before sidecar_verified_offset) and _spot_check_tail would
    verify only the events BEFORE the garbage, report OK, and
    the garbage line would sit undetected in the "verified"
    region forever. The tri-state signal closes that.
    """
    out: list[tuple[int, Event]] = []
    try:
        for end_off, line_text, torn in _iter_lines_with_offsets(
            events_path, start_offset=start_offset
        ):
            if torn:
                return out, True, True
            if end_off > end_offset:
                return out, False, True
            stripped = line_text.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                event = Event.from_canonical_dict(data)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError):
                # Middle-line parse failure inside the tail window
                # -- inconclusive; caller falls back to cold verify.
                return out, False, False
            out.append((end_off, event))
    except (ChainBrokenError, UnicodeDecodeError):
        # Middle-line corruption in the window -- inconclusive.
        return out, False, False
    return out, False, True


def _find_backwards_window_start(
    events_path: Path, *, file_size: int, target_events: int
) -> int:
    """Return a byte offset near the file's tail such that reading
    forward yields at least ``target_events`` complete events (or
    the whole file if it is shorter than the initial window).

    Strategy: start with a 64 KiB tail window (empirically covers
    ~30-300 events at typical event sizes); if the resulting count
    is < target, double the window until the file start is
    reached. Bounded: at most O(log(file_size / initial_window))
    expansions.
    """
    initial = 64 * 1024
    window = initial
    while True:
        start = max(0, file_size - window)
        # Count newlines from start to end -- each newline ends a
        # complete line. A conservative estimate; malformed lines
        # will surface later.
        try:
            with open(events_path, "rb") as fp:
                fp.seek(start)
                blob = fp.read(file_size - start)
        except OSError:
            return start
        # Advance start past the first partial line to align on a
        # line boundary (unless start == 0).
        if start > 0:
            idx = blob.find(b"\n")
            if idx == -1:
                # No newline in the window -- our window fell
                # inside one large line. Double or clamp.
                if start == 0:
                    return 0
                window = min(window * 2, file_size)
                continue
            aligned_start = start + idx + 1
        else:
            aligned_start = 0
        newline_count = (
            blob.count(b"\n") if start == 0 else blob[idx + 1 :].count(b"\n")
        )
        if newline_count >= target_events or start == 0:
            return aligned_start
        window = min(window * 2, file_size)


def _spot_check_tail(
    events_path: Path,
    *,
    sidecar_head_hex: str | None,
    sidecar_verified_offset: int,
    n: int = WARM_SPOT_CHECK_EVENTS,
) -> tuple[bool, str]:
    """Cheap tail-tamper defense (Ox Alpha co-build Fork 1 (b)).

    O(n events), never O(file_size). Two questions answered:

    A. Does the event that ENDS at ``sidecar_verified_offset``
       have a hash equal to ``sidecar_head_hex``? If not, the
       sidecar is either stale or forged -- fall back to cold
       verify.
    B. Do the last ``n`` events in the file rehash + chain
       correctly among themselves? Catches the near-tail tamper
       shape (attacker rewrote a recent event's payload but did
       not recompute the whole chain forward).

    Returns ``(ok, reason)``. On mismatch the warm path aborts.

    Special cases:
    - Empty file OR verified_offset == 0: no anchoring event to
      check; skip check A. Check B still runs on whatever tail
      exists.
    - Very short file (fewer than 2 events): trivial chain check,
      still runs.
    """
    try:
        file_size = events_path.stat().st_size
    except OSError as exc:
        return False, f"stat failed: {exc}"
    if file_size == 0:
        return True, "empty file; spot-check trivially ok"
    try:
        window_start = _find_backwards_window_start(
            events_path, file_size=file_size, target_events=n + 1
        )
    except OSError as exc:
        return False, f"spot-check window search failed: {exc}"
    events, hit_torn, complete = _read_events_in_range(
        events_path,
        start_offset=window_start,
        end_offset=file_size,
    )
    # SP amendment (Ox Alpha A Q1 adjacent DEFECT): a middle-line
    # parse failure in the tail window is evidence of corruption
    # or tamper -- spot-check MUST refuse to trust the sidecar
    # and force cold verify. Pre-amendment we silently verified
    # only the prefix before the failure and returned OK,
    # leaving the garbage line permanently undetected in the
    # warm-verified region.
    if not complete:
        return False, (
            "tail window contains a malformed line before end of "
            "range; spot-check inconclusive -- cold verify required"
        )
    if not events:
        return True, "not enough events for spot-check"
    # Trim to last n.
    if len(events) > n:
        events = events[-n:]
    # Check B: rehash + chain-link every event in the window.
    for i, (_end_off, ev) in enumerate(events):
        recomputed = hash_event(
            kind=ev.kind,
            payload=ev.payload,
            prev_hash=ev.prev_hash,
            id_bytes=ev.id,
            run_id=ev.run_id,
            step_id=ev.step_id,
            parent_id=ev.parent_id,
            timestamp_ns=ev.timestamp_ns,
        )
        if recomputed != ev.hash:
            return (
                False,
                f"tail event at spot-check index {i} rehashes to "
                f"{recomputed.hex()[:12]}...; declares "
                f"{ev.hash.hex()[:12]}...",
            )
        if i > 0 and ev.prev_hash != events[i - 1][1].hash:
            return (
                False,
                f"tail event at spot-check index {i} prev_hash "
                f"{ev.prev_hash.hex()[:12]}... does not chain to "
                f"prior {events[i - 1][1].hash.hex()[:12]}...",
            )
    # Check A: locate the event ending at sidecar_verified_offset
    # and confirm its hash matches sidecar_head_hex.
    if sidecar_head_hex is not None and sidecar_verified_offset > 0:
        anchor_hit = False
        for end_off, ev in events:
            if end_off == sidecar_verified_offset:
                if ev.hash.hex() != sidecar_head_hex:
                    return (
                        False,
                        f"sidecar head {sidecar_head_hex[:12]}... does "
                        f"not match event ending at offset "
                        f"{sidecar_verified_offset} "
                        f"({ev.hash.hex()[:12]}...)",
                    )
                anchor_hit = True
                break
        if not anchor_hit:
            # verified_offset is outside our tail window. That is
            # legitimate for very-old sidecars against a big
            # appended file. We cannot cheaply confirm here; the
            # subsequent replay walk starting from verified_offset
            # would still fail if the first delta event's
            # prev_hash != sidecar_head. So permit the warm path.
            return True, (
                "spot-check ok (sidecar offset outside tail window; "
                "delta-replay will catch head-mismatch)"
            )
    return True, "spot-check ok"


def verify_trace(
    events_path: Path | str,
    *,
    run_id_hex: str | None = None,
    sidecar_path: Path | str | None = None,
    force_cold: bool = False,
    persist: bool = True,
) -> TraceVerifyResult:
    """Warm verify: reuse a sidecar checkpoint if available.

    - ``run_id_hex``: the run whose trace we are verifying. When
      None, the run_id is bound from the FIRST event's run_id
      (cold path); a sidecar lookup requires an explicit
      ``run_id_hex`` because the sidecar path is
      ``.ract/trace/{run_id}.verify.json``.
    - ``sidecar_path``: override the default path (test hook).
    - ``force_cold``: skip the sidecar entirely; cold-verify.
      Operators pass this via ``ract trace verify --cold`` when
      tamper is suspected.
    - ``persist``: on VALID + TORN_TAIL update the sidecar. On
      TAMPERED the sidecar is left untouched (an attacker who
      forced a false-VALID result would have needed to forge
      the sidecar; forcing us NOT to write on tamper avoids
      overwriting an operator's forensic marker).
    """
    p = Path(events_path)
    if not p.is_file():
        return TraceVerifyResult.valid(
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            reason=f"trace file {p} does not exist (nothing to verify)",
        )
    if run_id_hex is None or force_cold:
        result = cold_verify(p)
        if persist and result.is_valid and run_id_hex is not None:
            _persist_sidecar_after_verify(
                events_path=p,
                sidecar_path=sidecar_path,
                run_id_hex=run_id_hex,
                result=result,
            )
        return result
    resolved_sidecar = (
        Path(sidecar_path)
        if sidecar_path is not None
        else _sidecar_path_for(p, run_id_hex)
    )
    body = _read_verify_sidecar(
        sidecar_path=resolved_sidecar, expected_run_id_hex=run_id_hex
    )
    if body is None:
        # Cold path: no sidecar, header refused, or shape-invalid.
        result = cold_verify(p)
    else:
        start_offset = int(body["last_verified_offset"])
        events_prior = int(body["last_verified_events"])
        head_hex = body["last_verified_head"]
        # Ox Alpha co-build Fork 1 (b): near-tail spot-check
        # BEFORE trusting the sidecar's verified_head. Catches
        # the dominant tamper shape (edit near-tail + bump
        # offset) at ~64 hash ops. Mid-file tamper is NOT
        # detected here -- that gap belongs to external
        # anchoring (v0.6 backlog).
        spot_ok, spot_reason = _spot_check_tail(
            p,
            sidecar_head_hex=head_hex,
            sidecar_verified_offset=start_offset,
            n=WARM_SPOT_CHECK_EVENTS,
        )
        if not spot_ok:
            _LOG.warning(
                "trace verify sidecar %s failed tail spot-check "
                "(%s); cold-verify fallback",
                resolved_sidecar,
                spot_reason,
            )
            _emit_verify_completed_event(
                run_id=run_id_hex,
                result=TraceVerifyResult.invalid(
                    reason=f"tail spot-check refused sidecar: {spot_reason}"
                ),
                mode="spot_check_refused",
            )
            return cold_verify(p)
        # Reconstitute the chain: tip_hash comes from the sidecar;
        # run_id comes from the caller (warm path REQUIRES
        # run_id_hex up front).
        try:
            run_id_bytes = bytes.fromhex(run_id_hex)
        except ValueError as exc:
            raise ValueError(
                f"verify_trace: run_id_hex {run_id_hex!r} is not valid hex"
            ) from exc
        if len(run_id_bytes) != 16:
            raise ValueError(
                f"verify_trace: run_id_hex must decode to 16 bytes; "
                f"got {len(run_id_bytes)}"
            )
        chain = EventChain(run_id=run_id_bytes)
        if head_hex is not None:
            try:
                chain.tip_hash = bytes.fromhex(head_hex)
            except ValueError:
                # Sidecar corrupt head_hex; fall back to cold.
                _LOG.warning(
                    "trace verify sidecar %s head_hex invalid; cold-verify fallback",
                    resolved_sidecar,
                )
                return cold_verify(p)
        file_size = p.stat().st_size
        if start_offset > file_size:
            # File shrank (repair / rotation / operator hand-edit);
            # sidecar is now inconsistent with the file. Cold-verify.
            _LOG.warning(
                "trace verify sidecar %s claims offset %d but file %s is only %d bytes; "
                "cold-verify fallback",
                resolved_sidecar,
                start_offset,
                p,
                file_size,
            )
            return cold_verify(p)
        _emit_incremental_resumed_event(
            run_id=run_id_hex,
            last_offset=start_offset,
            file_size=file_size,
        )
        try:
            result = _walk_verify(
                events_path=p,
                chain=chain,
                start_offset=start_offset,
                events_verified_prior=events_prior,
            )
        except (OSError, UnicodeDecodeError, ChainBrokenError) as exc:
            # SP amendment (Ox Alpha A Q4 defect fold, warm-path
            # variant): surface as INVALID / TAMPERED so warm
            # callers get a dataclass instead of a raise.
            if isinstance(exc, OSError):
                result = TraceVerifyResult.invalid(
                    reason=f"trace file {p} unreadable: {exc}",
                )
            else:
                result = TraceVerifyResult.tampered(
                    verified_head=None,
                    verified_offset=start_offset,
                    events_verified=events_prior,
                    tamper_details={
                        "offset": start_offset,
                        "event_index": events_prior,
                        "kind": (
                            "middle_utf8_corruption"
                            if isinstance(exc, UnicodeDecodeError)
                            else "chain_broken"
                        ),
                        "reason": str(exc),
                    },
                    reason=f"{type(exc).__name__} at offset {start_offset}: {exc}",
                )
    _emit_verify_completed_event(
        run_id=run_id_hex,
        result=result,
        mode="warm" if body is not None else "cold",
    )
    if persist and result.is_valid:
        _persist_sidecar_after_verify(
            events_path=p,
            sidecar_path=sidecar_path,
            run_id_hex=run_id_hex,
            result=result,
        )
    return result


def _persist_sidecar_after_verify(
    *,
    events_path: Path,
    sidecar_path: Path | str | None,
    run_id_hex: str,
    result: TraceVerifyResult,
) -> None:
    resolved = (
        Path(sidecar_path)
        if sidecar_path is not None
        else _sidecar_path_for(events_path, run_id_hex)
    )
    try:
        _write_verify_sidecar(
            sidecar_path=resolved,
            run_id_hex=run_id_hex,
            verified_head=result.verified_head,
            verified_offset=result.verified_offset,
            events_verified=result.events_verified,
        )
    except OSError as exc:  # noqa: BLE001 -- perf primitive; log + continue
        _LOG.warning(
            "trace verify sidecar %s could not be persisted (%s); "
            "next verify will cold-start",
            resolved,
            exc,
        )


def persist_verify_sidecar(
    *,
    events_path: Path,
    run_id_hex: str,
    result: TraceVerifyResult,
    sidecar_path: Path | None = None,
) -> None:
    """Public helper: persist a verify result to the sidecar.

    Used by callers who ran cold_verify explicitly and want to
    warm-prime the sidecar for future verifies. No-op unless the
    result is valid (VALID or TORN_TAIL).
    """
    if not result.is_valid:
        return
    _persist_sidecar_after_verify(
        events_path=events_path,
        sidecar_path=sidecar_path,
        run_id_hex=run_id_hex,
        result=result,
    )


# ---------------------------------------------------------------------------
# Observability event emit (via ract.trace.sink; safe to fail)
# ---------------------------------------------------------------------------


def _emit_torn_tail_event(events_path: Path, offset: int, raw_repr: str) -> None:
    try:
        from ract.trace.sink import emit

        emit(
            "trace.torn_tail_detected",
            {
                "path": str(events_path),
                "offset": int(offset),
                "raw_repr": raw_repr[:200],
            },
        )
    except Exception:  # noqa: BLE001 -- observability failure never breaks verify
        _LOG.debug("trace.torn_tail_detected emit failed", exc_info=True)


def _emit_incremental_resumed_event(
    *, run_id: str, last_offset: int, file_size: int
) -> None:
    try:
        from ract.trace.sink import emit

        emit(
            "trace.incremental_verify_resumed",
            {
                "run_id": run_id,
                "last_offset": int(last_offset),
                "file_size": int(file_size),
                "new_bytes": int(max(0, file_size - last_offset)),
            },
        )
    except Exception:  # noqa: BLE001
        _LOG.debug("trace.incremental_verify_resumed emit failed", exc_info=True)


def _emit_verify_completed_event(
    *, run_id: str | None, result: TraceVerifyResult, mode: str
) -> None:
    try:
        from ract.trace.sink import emit

        emit(
            "trace.verify_completed",
            {
                "run_id": run_id or "",
                "mode": mode,
                "status": result.status,
                "events_verified": int(result.events_verified),
                "events_torn": int(result.events_torn),
                "events_tampered": int(result.events_tampered),
                "verified_offset": int(result.verified_offset),
            },
        )
    except Exception:  # noqa: BLE001
        _LOG.debug("trace.verify_completed emit failed", exc_info=True)


__all__ = [
    "TRACE_VERIFY_SIDECAR_SCHEMA",
    "TRACE_VERIFY_SIDECAR_TYPE",
    "TraceVerifyResult",
    "TraceVerifyStatus",
    "cold_verify",
    "persist_verify_sidecar",
    "verify_trace",
]


# RACT 0.5.2 module_05
