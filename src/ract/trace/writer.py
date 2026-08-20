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

    @property
    def run_id(self) -> bytes:
        """The run id this writer stamps into every event."""
        return self.chain.run_id

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

        Raises ``ChainBrokenError`` if any middle event has been tampered
        with or if the chain's tip does not link cleanly.
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
        """Iterate the log's events (unverified)."""
        p = Path(path)
        if not p.is_file():
            return
        with p.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                data = json.loads(line)
                yield Event.from_canonical_dict(data)

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
