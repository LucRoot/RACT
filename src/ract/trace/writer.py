"""JsonlEventWriter + EventReader — durable trace on disk.

SUBSTRATE §6.4. The writer appends canonical-JSON events (one per line,
sorted keys) to ``evals/runs/<run_id>/events.jsonl``. The reader replays
the file into an ``EventChain`` while re-verifying every hash link.

Lateral chain branch C: the writer honours an optional
``RedactionProfile`` (patterns loaded from ``ract.yaml``) so ``prompt.sent``
and other operator-facing payloads can be scrubbed before write. Off by
default.

Thread-safety contract: SUBSTRATE §3.2 (worktree-per-step) already
serialises writes per run — one loop, one writer, one file. The writer
takes a ``threading.Lock`` anyway so a caller who spawns a thread to
emit an ambient event (e.g. an in-flight tool refusal) does not corrupt
the JSONL. See ``docs/ARCHITECTURE.md`` §"Concurrent tool execution".
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from ract.canonical import dumps_jcs

from ract.trace.events import (
    ChainBrokenError,
    Event,
    EventChain,
    EventKind,
    hash_event,
)

_LOG = logging.getLogger("ract.trace.writer")


# ---------------------------------------------------------------------------
# Write-first invariant guard
# ---------------------------------------------------------------------------


class WriteFirstViolation(RuntimeError):
    """Raised when an observer is invoked before durability completes.

    v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). The spec's
    write-first invariant (04-RACT-DESIGN §5.1.2) states: *"no state
    change is observable to any component until the corresponding
    event is durably written to the log."* This exception is the
    runtime enforcer: any observer notification path invoked while
    :class:`JsonlEventWriter` is mid-commit (between build_next and
    fsync-return) raises it, so a future refactor that reorders the
    commit sequence surfaces the invariant break loudly instead of
    silently letting an observer see an event that has not yet
    reached disk.

    Not currently reachable through the public API — the writer's
    own emit() path structurally serialises fsync-before-observer.
    The guard exists to catch REGRESSIONS: an observer that
    re-enters the writer, a wrapper that mirrors an event through a
    pre-commit hook, a subclass that overrides _write_line, all
    would surface here rather than silently violating the invariant.
    """


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedactionProfile:
    """A shallow pattern-scrub applied before write.

    ``patterns`` are regex strings; each match in a payload value is
    replaced with ``replacement``. ``fields`` names payload keys whose
    values are fully redacted regardless of pattern (e.g. ``api_key``).
    Scoping: only string values are scanned; nested dicts and lists are
    walked recursively.

    This is deliberately shallow (see module_05 flagged gaps). A
    production redactor would parse tool-specific formats and apply
    entity-aware masking; the profile here is a first line of defence
    for shared logs, not a data-loss-prevention layer.
    """

    patterns: tuple[str, ...] = field(default_factory=tuple)
    fields: tuple[str, ...] = field(default_factory=tuple)
    replacement: str = "[REDACTED]"

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a redacted copy of ``payload``."""
        compiled = [re.compile(p) for p in self.patterns]
        field_set = set(self.fields)

        def _scrub(value: Any, key: str | None = None) -> Any:
            if key is not None and key in field_set:
                return self.replacement
            if isinstance(value, str):
                out = value
                for regex in compiled:
                    out = regex.sub(self.replacement, out)
                return out
            if isinstance(value, dict):
                return {k: _scrub(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [_scrub(v) for v in value]
            if isinstance(value, tuple):
                return tuple(_scrub(v) for v in value)
            return value

        return {k: _scrub(v, k) for k, v in payload.items()}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class JsonlEventWriter:
    """Append canonical events to ``<path>`` and to the in-memory chain.

    ``path`` is created (parents included) on first write. Each call to
    ``emit`` builds the next chained event, writes its JSON line to the
    file, and appends to the ``EventChain``.
    """

    def __init__(
        self,
        path: Path | str,
        run_id: bytes | None = None,
        *,
        redaction: RedactionProfile | None = None,
        repair_on_open: bool = False,
    ) -> None:
        # v0.5.1 module_06: the writer's run_id is the load-bearing
        # stamp on every emitted event. When the caller passes
        # ``None`` the ambient run_id
        # (:func:`ract.runtime.get_current_run_id`, hex string) is
        # decoded into the 16-byte shape ``EventChain`` requires. When
        # no ambient is bound the writer refuses -- an event log with
        # no run_id is a control-bypass, not a valid fallback.
        if run_id is None:
            from ract.runtime import get_current_run_id

            ambient_hex = get_current_run_id()
            if not ambient_hex:
                raise ValueError(
                    "JsonlEventWriter requires an explicit run_id or a bound "
                    "ambient run_id (see ract.runtime.bind_run_id)"
                )
            try:
                run_id = bytes.fromhex(ambient_hex)
            except ValueError as exc:
                raise ValueError(
                    f"ambient run_id {ambient_hex!r} is not a valid hex string; "
                    "JsonlEventWriter needs 32 hex chars = 16 bytes"
                ) from exc
            if len(run_id) != 16:
                raise ValueError(
                    f"ambient run_id {ambient_hex!r} decoded to "
                    f"{len(run_id)} bytes; JsonlEventWriter needs 16"
                )
        self.path = Path(path)
        self.chain = EventChain(run_id=run_id)
        self._redaction = redaction
        self._lock = threading.Lock()
        # v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Two
        # observer classes per 04-RACT-DESIGN §5.1.2:
        #   * post-commit observers -- fire-and-forget best-effort
        #     after fsync return; a raise here is WARN-logged, not
        #     propagated to the emit() caller.
        #   * durability observers -- awaited when the caller
        #     explicitly calls checkpoint(); their failure IS
        #     propagated so a consumer needing "this event has
        #     propagated to secondary storage" can know.
        # The legacy _mirror_sinks surface (module_05 OTEL exporter
        # etc.) is retained and routed through the post-commit path
        # so add_mirror() callers see no behavior change.
        self._mirror_sinks: list[Any] = []
        self._post_commit_observers: list[Callable[[Event], Any]] = []
        self._durability_observers: list[Callable[[Event], Any]] = []
        # WriteFirstViolation guard: True while we're between
        # build_next and fsync-return. Any observer notification
        # attempted in that window raises. See :class:`WriteFirstViolation`.
        self._committing: bool = False
        # Checkpoint watermark: index into self.chain.events at the
        # last :meth:`checkpoint` call. Durability observers fire on
        # events[watermark:] then the watermark advances.
        self._checkpoint_watermark: int = 0
        # v0.5.1 spec-completeness module_03: repair summary from the
        # most recent :meth:`repair_from_disk` invocation (None until
        # a repair has run). Exposed for observability + tests.
        self.last_repair_summary: Any = None
        # v0.5.1 module_09 (Lens F H1 closure): seed the chain's
        # tip_hash from the on-disk tail if the events.jsonl file
        # already carries events. Without this, a second writer opened
        # on the same file (crash-restart, repair tool, second loop
        # under the same run_id) would default to ``_GENESIS_HASH``,
        # produce a first event with ``prev_hash = 0*32``, and
        # silently break the chain -- ``EventReader.load`` would then
        # raise ChainBrokenError on the NEXT read.
        #
        # A tail-only replay is sufficient: reading the LAST line of
        # the JSONL gives us the current ``hash`` value, which is what
        # the next event's ``prev_hash`` must reference. Middle-line
        # corruption is deferred to ``EventReader.load`` (which walks
        # the full file and re-verifies every hash link).
        #
        # Tail-corruption (Lens F H2 closure): if the last line fails
        # to parse we fall back to the second-to-last event's hash and
        # WARN -- matching the manifest_ledger / WAL / workspace-chain
        # tolerant idiom. Genesis (empty file) stays GENESIS.
        self._reseed_tip_from_disk()
        # v0.5.1 spec-completeness module_03: opt-in repair on open.
        # Default OFF -- automatic repair is aggressive because it
        # writes new events during __init__. Callers who want to
        # resume after a crash pass repair_on_open=True. The repair
        # is idempotent so a second open with repair_on_open=True
        # will not double-close already-repaired handles.
        if repair_on_open:
            self.repair_from_disk()

    @property
    def run_id(self) -> bytes:
        """The run id this writer stamps into every event."""
        return self.chain.run_id

    def _reseed_tip_from_disk(self) -> None:
        """Replay the on-disk tail so ``self.chain.tip_hash`` matches disk.

        v0.5.1 module_09 (Lens F H1 closure). Called from
        ``__init__``; a fresh (missing or zero-byte) file leaves the
        chain's default GENESIS tip in place. A well-formed tail line
        seeds ``tip_hash`` from its ``hash`` field. A malformed tail
        line falls back to the second-to-last well-formed line's hash
        (Lens F H2 tail-tolerant alignment) and WARN-logs so the
        operator sees the recovery.

        The full-chain re-verification is intentionally deferred to
        :meth:`EventReader.load` -- that path already re-hashes every
        event to catch middle-line tamper. Re-running it in the
        writer's hot construction path would add O(N) startup on
        every reopen, which is a real cost for long-running loops.
        """
        # SP Q6 [NIT] amendment: collapse the stat() + read_bytes()
        # TOCTOU pair into a single read_bytes() call; a concurrent
        # writer growing/shrinking the file between the two syscalls
        # cannot then mislead the seed decision. A missing file
        # (post-stat unlink) surfaces as FileNotFoundError; a permission
        # flip surfaces as PermissionError. Both are handled below.
        if not self.path.is_file():
            return
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            _LOG.warning(
                "JsonlEventWriter: could not read %s to reseed tip_hash "
                "(errno=%r); starting from GENESIS. New appends will "
                "break the chain if the file already carries events.",
                self.path,
                exc,
            )
            return
        if not raw:
            return
        # SP Q6 [DEFECT] amendment: a UTF-8 decode failure on the
        # events.jsonl file means the on-disk state is unreadable by
        # the writer. Falling through to GENESIS would silently break
        # the chain (the new writer would append with prev_hash=0*32
        # while the file already carries hex-encoded event lines whose
        # tail hash disagrees). Refuse construction instead -- the
        # operator inspects and repairs before the writer produces
        # bytes.
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ChainBrokenError(
                f"JsonlEventWriter: {self.path} is not valid UTF-8 "
                f"({exc}); refusing to reseed to GENESIS because that "
                "would silently break the chain. Inspect the file and "
                "repair (or delete + restart the run) before reopening."
            ) from exc
        lines = [line for line in text.split("\n") if line.strip()]
        if not lines:
            return
        # Walk from the tail forward: the FIRST parseable line from
        # the end wins. Malformed tail lines are dropped with WARN
        # (Lens F H2 alignment with the WAL/manifest-ledger tolerant
        # pattern). Middle-line corruption is not detected here --
        # ``EventReader.load`` is the full-verify surface.
        dropped_tail = 0
        seed_hash: bytes | None = None
        for candidate in reversed(lines):
            try:
                data = json.loads(candidate)
                event = Event.from_canonical_dict(data)
                seed_hash = event.hash
                break
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                dropped_tail += 1
                _LOG.warning(
                    "JsonlEventWriter: %s tail line dropped (torn "
                    "write?): %s. Falling back to prior line.",
                    self.path,
                    exc,
                )
        if seed_hash is None:
            _LOG.warning(
                "JsonlEventWriter: %s has %d line(s) but none parse as "
                "an Event; starting from GENESIS. New appends will "
                "break the chain until the file is repaired.",
                self.path,
                len(lines),
            )
            return
        self.chain.tip_hash = seed_hash
        if dropped_tail:
            _LOG.warning(
                "JsonlEventWriter: %s reseeded tip_hash after "
                "dropping %d torn tail line(s).",
                self.path,
                dropped_tail,
            )

    def add_mirror(self, sink: Any) -> None:
        """Register an additional sink invoked with each appended event.

        ``sink(event)`` is called after the event lands on disk; a raise
        from a sink surfaces to the caller so a broken mirror is not
        silently swallowed.

        v0.5.1 spec-completeness module_03: retained for backward
        compat. Legacy mirror sinks fire on the post-commit path
        (after fsync-return, after lock-release). A raise from a
        legacy mirror still surfaces to the emit() caller -- this is
        the historical semantics used by the OTEL exporter, which
        needs to know when it fails. New callers should prefer
        :meth:`add_post_commit_observer` (raises are logged, not
        propagated) or :meth:`add_durability_observer` (raises
        propagate only from checkpoint()).
        """
        self._mirror_sinks.append(sink)

    def add_post_commit_observer(self, observer: Callable[[Event], Any]) -> None:
        """Register a best-effort post-commit observer.

        v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Per
        04-RACT-DESIGN §5.1.2 "Two observer classes": post-commit
        observers are best-effort -- they run after the event lands
        on disk (fsync-return + lock-release) and their failures are
        logged but do not affect the commit. Failure to notify a
        post-commit observer does NOT re-raise to the emit() caller.

        Use for: TUI updates, telemetry sidecars, dev-time inspect
        panels. See §Q8 (TUI as post-commit observer).
        """
        self._post_commit_observers.append(observer)

    def add_durability_observer(self, observer: Callable[[Event], Any]) -> None:
        """Register a durability observer awaited during :meth:`checkpoint`.

        v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Per
        04-RACT-DESIGN §5.1.2 "Two observer classes": durability
        observers are for consumers who need to know the event has
        propagated to secondary storage (e.g. an index feeder, a
        replicated log, another agent's inbox). They fire when the
        caller explicitly calls :meth:`checkpoint`. Failure of a
        durability observer during checkpoint IS propagated so the
        caller can react.

        Note: durability observers are NOT invoked from emit(); only
        from checkpoint(). A high-frequency emit path pays no
        durability-observer cost. See §5.1.2 three-indices-as-
        durability-observer example.
        """
        self._durability_observers.append(observer)

    def checkpoint(self) -> None:
        """Fire durability observers for every event since the last checkpoint.

        v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Per
        04-RACT-DESIGN §5.1.2 checkpoint pattern (adapted to RACT's
        sync world -- spec uses asyncio; RACT does not). Iterates
        every event in ``self.chain.events`` since the last
        checkpoint watermark and notifies each durability observer
        exactly once per event.

        Failure of a durability observer surfaces to the caller so a
        consumer needing "this event has propagated to my index" can
        know when the propagation failed. Post-commit observers are
        NOT invoked here -- they've already fired at emit-time (fire-
        and-forget best-effort).
        """
        if self._committing:
            raise WriteFirstViolation(
                "checkpoint() invoked while a commit is in progress; "
                "the write-first invariant forbids observing state "
                "before the event is durably written"
            )
        with self._lock:
            new_events = self.chain.events[self._checkpoint_watermark:]
            self._checkpoint_watermark = len(self.chain.events)
        # Fire observers OUTSIDE the lock -- a slow observer must not
        # block subsequent emits. This matches spec §5.1.2 which
        # awaits observers only from checkpoint(), not append().
        for event in new_events:
            for observer in self._durability_observers:
                observer(event)  # raises propagate; caller wants to know

    def emit(
        self,
        kind: EventKind,
        payload: dict[str, Any],
        *,
        step_id: bytes | None = None,
        parent_id: bytes | None = None,
        timestamp_ns: int | None = None,
    ) -> Event:
        """Emit one event; return the persisted ``Event`` value.

        v0.5.1 spec-completeness module_03 (Lens 2 Delta 1) commit
        sequence (per 04-RACT-DESIGN §5.1.2):
            1. Acquire commit lock (+ set _committing flag).
            2. Assign sequence (via EventChain.build_next).
            3. Durably write to storage (write + flush + fsync).
            4. Append to in-memory chain (advance tip_hash).
            5. Clear _committing flag + release lock.
            6. Fire post-commit observers (best-effort; raises logged).
            7. Return event.

        Durability observers are NOT fired here -- they fire only
        from :meth:`checkpoint`. This preserves the low-latency
        emit() path.
        """
        if self._redaction is not None:
            payload = self._redaction.apply(payload)
        with self._lock:
            self._committing = True
            try:
                event = self.chain.build_next(
                    kind=kind,
                    payload=payload,
                    step_id=step_id,
                    parent_id=parent_id,
                    timestamp_ns=timestamp_ns,
                )
                self._write_line(event)  # includes flush + fsync
                self.chain.append(event)
            finally:
                self._committing = False
        # Post-commit observers fire outside the lock, after
        # durability. Legacy mirror sinks first (backward compat --
        # raises propagate). New post-commit observers second
        # (raises logged, not propagated).
        for sink in self._mirror_sinks:
            sink(event)
        for observer in self._post_commit_observers:
            try:
                observer(event)
            except Exception as exc:  # noqa: BLE001 -- best-effort
                _LOG.warning(
                    "post-commit observer %r raised on event %s: %s",
                    observer,
                    event.kind,
                    exc,
                )
        return event

    def _write_line(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # v0.5.1 module_03: JSONL trace lines are RFC 8785 JCS bytes
        # so a hash re-verification path can bytes-compare the on-disk
        # line to :func:`canonical_payload_bytes` output.
        line = dumps_jcs(event.to_canonical_dict()).decode("utf-8")
        # v0.5.1 spec-completeness module_03: fsync inside the lock
        # is the write-first invariant (04-RACT-DESIGN §5.1.2). The
        # context-manager close alone flushes the Python buffer to
        # the OS, not the OS buffer to disk; a SIGKILL between close
        # and fsync loses the last event and any post-commit
        # observer would then have seen "state changed" without a
        # durable record. Ordering: write -> flush -> fsync -> return.
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())

    def repair_from_disk(self) -> Any:
        """Read the on-disk log, run :func:`repair`, append synthesized closes.

        v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). See
        :mod:`ract.trace.repair`. Idempotent: a second call on the
        same log adds nothing (all opens already have deterministic
        closes). Sets :attr:`last_repair_summary` on this writer.

        Returns the :class:`RepairedEventStream` (contains the
        summary + synthesized events).

        Concurrency contract (SP Q6 amendment): the entire read ->
        compute -> write sequence is held under :attr:`_lock` so an
        ambient thread that calls :meth:`emit` mid-repair blocks
        until repair finishes. Without this barrier, a concurrent
        emit() between the read and the write of synthesized closes
        would chain from a stale tip_hash and fork the chain. The
        SUBSTRATE §3.2 single-writer-per-run invariant already
        forbids the cross-process shape; this lock closes the
        in-process ambient-thread shape.
        """
        from ract.trace.repair import repair  # local import: avoid cycle

        # SP Q6 + Q7 DEFECT 1 fold: hold the commit lock for the
        # entire read-compute-write transaction. Repair is a rare
        # operation (invoked only on writer open or via
        # `ract trace repair --apply`); blocking emits during repair
        # is the correct trade-off vs a chain-fork race.
        with self._lock:
            existing = list(EventReader.iter_events(self.path))
            stream = repair(existing)
            self.last_repair_summary = stream.repair_summary
            # If repair produced no synthesized events, nothing to
            # write. We still return the (already-recorded) summary.
            if not stream.synthesized_close_events:
                return stream
            # Append synth events to the on-disk log AND to the
            # in-memory chain. The synthesized events already have
            # valid hashes chained from the last existing event's
            # hash (repair() computed them from EventReader's tail).
            self._committing = True
            try:
                for synth in stream.synthesized_close_events:
                    self._write_line(synth)
                    self.chain.append(synth)
            finally:
                self._committing = False
        return stream

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Drain durability observers via :meth:`checkpoint`.

        v0.5.1 spec-completeness module_03 SP Q7 NIT fold: previously
        a no-op stub for ``contextlib.closing`` compatibility. Now
        invokes checkpoint() so a caller that closes without an
        explicit checkpoint still sees durability observers fire on
        every event emitted during the writer's lifetime. Idempotent:
        a close() after a prior checkpoint() finds no new events
        past the watermark and does nothing.

        Failure of a durability observer during close-time checkpoint
        propagates to the caller (matches :meth:`checkpoint`
        semantics -- the caller wants to know when a downstream
        durability observer failed).
        """
        self.checkpoint()


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


@dataclass
class EventReader:
    """Load and verify an event log."""

    @staticmethod
    def load(path: Path | str) -> EventChain:
        """Replay ``path`` into an ``EventChain`` with full hash verification.

        Middle-line JSON errors raise :class:`ChainBrokenError` (the
        chain has been tampered with mid-stream). A malformed tail
        line -- for example a SIGKILL mid-``fh.write("\\n")`` -- is
        WARN-logged and DROPPED so the run's event log stays
        recoverable up to the last durable event.

        v0.5.1 module_09 (Lens F H2 closure): the prior behavior
        raised on any tail parse error, making the event log the ONLY
        ledger in the repo without a tolerant tail policy. The
        manifest ledger, WAL, workspace-digest chain, and suite chain
        all recover; the event log now matches that idiom.
        """
        events = list(EventReader.iter_events(path))
        if not events:
            raise ChainBrokenError(f"event log {path!s} is empty; cannot infer run_id")
        chain = EventChain(run_id=events[0].run_id)
        for event in events:
            # ``EventChain.append`` re-hashes the payload and validates
            # the ``prev_hash`` link, which is the tamper check.
            chain.append(event)
        return chain

    @staticmethod
    def iter_events(path: Path | str) -> Iterable[Event]:
        """Iterate the log's events (middle-strict, tail-tolerant).

        v0.5.1 module_09 (Lens F H2 closure): a malformed tail line is
        WARN-logged + dropped so a torn-write crash leaves the file
        readable. A malformed middle line raises
        :class:`ChainBrokenError` -- non-append corruption is still a
        hard failure.
        """
        p = Path(path)
        if not p.is_file():
            return
        raw = p.read_text(encoding="utf-8")
        lines = raw.split("\n")
        # Trim trailing empty line (JSONL framing).
        if lines and lines[-1] == "":
            lines.pop()
        for i, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                if i == len(lines) - 1:
                    _LOG.warning(
                        "EventReader: %s tail line %d dropped (torn "
                        "write? %s). Middle events remain verifiable.",
                        p,
                        i,
                        exc,
                    )
                    return
                raise ChainBrokenError(
                    f"malformed middle event line {i} in {p}: {exc}"
                ) from exc
            try:
                yield Event.from_canonical_dict(data)
            except (ValueError, KeyError, TypeError) as exc:
                if i == len(lines) - 1:
                    _LOG.warning(
                        "EventReader: %s tail line %d dropped (shape "
                        "invalid? %s).",
                        p,
                        i,
                        exc,
                    )
                    return
                raise ChainBrokenError(
                    f"malformed middle event at line {i} in {p}: {exc}"
                ) from exc

    @staticmethod
    def verify(path: Path | str) -> tuple[bool, str]:
        """Return ``(ok, reason)`` — a diagnostic form of ``load``."""
        try:
            EventReader.load(path)
        except ChainBrokenError as exc:
            return False, str(exc)
        except FileNotFoundError as exc:
            return False, str(exc)
        return True, ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def rebuild_hash(event: Event) -> bytes:
    """Recompute an event's hash from its fields (used by tests)."""
    return hash_event(
        kind=event.kind,
        payload=event.payload,
        prev_hash=event.prev_hash,
        id_bytes=event.id,
        run_id=event.run_id,
        step_id=event.step_id,
        parent_id=event.parent_id,
        timestamp_ns=event.timestamp_ns,
    )


__all__ = [
    "EventReader",
    "JsonlEventWriter",
    "RedactionProfile",
    "WriteFirstViolation",
    "rebuild_hash",
]


# RACT 0.4.0
