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
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

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
        # Extra sinks the caller can attach (module_05 uses this to
        # mirror events to the OTLP exporter without coupling this
        # module to OpenTelemetry).
        self._mirror_sinks: list[Any] = []
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
        """
        self._mirror_sinks.append(sink)

    def emit(
        self,
        kind: EventKind,
        payload: dict[str, Any],
        *,
        step_id: bytes | None = None,
        parent_id: bytes | None = None,
        timestamp_ns: int | None = None,
    ) -> Event:
        """Emit one event; return the persisted ``Event`` value."""
        if self._redaction is not None:
            payload = self._redaction.apply(payload)
        with self._lock:
            event = self.chain.build_next(
                kind=kind,
                payload=payload,
                step_id=step_id,
                parent_id=parent_id,
                timestamp_ns=timestamp_ns,
            )
            self._write_line(event)
            self.chain.append(event)
        for sink in self._mirror_sinks:
            sink(event)
        return event

    def _write_line(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # v0.5.1 module_03: JSONL trace lines are RFC 8785 JCS bytes
        # so a hash re-verification path can bytes-compare the on-disk
        # line to :func:`canonical_payload_bytes` output.
        line = dumps_jcs(event.to_canonical_dict()).decode("utf-8")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def close(self) -> None:
        """No-op today; provided so callers can use ``contextlib.closing``."""


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
    "rebuild_hash",
]


# RACT 0.4.0
