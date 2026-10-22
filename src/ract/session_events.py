"""Session events: the one ordered stream a running session emits.

LR:: Before this module the session printed from wherever the code happened
to be, so nothing could be tested as a whole, headless output and a future
editor bridge had nothing to read, and a slow model meant silence. Every
consumer (the terminal renderer, ``--output-format stream-json``, the SDK)
now reads the same events in the same order. The schema is
``docs/EVENTS_SESSION.md``; ``KINDS`` below must match it, and a test
checks that it does.

Events are plain data: JSON-serialisable, print-safe text, no secrets, no
tracebacks. Every string goes through ``ract.redaction`` before the event
exists; streamed text goes through a ``StreamingRedactor`` (``TextWriter``),
which holds back the tail of each piece so a key split across two deltas is
still caught. Producers call ``EventStream.emit``; nothing here prints.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ract.redaction import StreamingRedactor, redact

SCHEMA_VERSION = 2

KINDS: frozenset[str] = frozenset(
    {
        "session.started",
        "session.resumed",
        "session.ended",
        "session.rewound",
        "mode.changed",
        "input.queued",
        "input.withdrawn",
        "turn.started",
        "turn.interrupting",
        "turn.finished",
        "plan.proposed",
        "step.started",
        "step.finished",
        "agent.text.delta",
        "agent.reasoning.delta",
        "agent.heartbeat",
        "agent.retry",
        "tool.call.started",
        "tool.call.finished",
        "diff.proposed",
        "diff.reviewed",
        "change.applied",
        "approval.requested",
        "approval.resolved",
        "cost.updated",
        "error.surfaced",
        "notice",
    }
)

# Named in docs/EVENTS_SESSION.md under "Reserved names": planned, not yet
# emitted. ``emit`` refuses them so nobody ships one early under a guess.
RESERVED_KINDS: frozenset[str] = frozenset(
    {
        "context.compacted",
        "verification.started",
        "verification.finished",
        "checkpoint.created",
        "mcp.server.started",
        "mcp.server.failed",
    }
)

MAX_DELTA_BYTES = 4096
HEARTBEAT_SECONDS = 2.0

# Control characters other than tab and newline would let event text move
# the cursor or rewrite earlier lines when printed.
_UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x80-\x9f]")


class UnknownEventKind(ValueError):
    """Raised when a producer emits a kind that is not in ``KINDS``."""


def safe_text(text: str) -> str:
    """Return ``text`` with control characters replaced, safe to print.

    A carriage return is dropped, not replaced: a model reply with CRLF line
    endings showed a replacement character before every line break (B-045).
    """
    return _UNSAFE.sub("�", text.replace("\r", ""))


def split_text(text: str, limit: int = MAX_DELTA_BYTES) -> list[str]:
    """Split ``text`` into pieces of at most ``limit`` UTF-8 bytes.

    Splits only at character boundaries, so every piece decodes on its own.
    """
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for ch in text:
        width = len(ch.encode("utf-8"))
        if size + width > limit and current:
            pieces.append("".join(current))
            current, size = [], 0
        current.append(ch)
        size += width
    if current:
        pieces.append("".join(current))
    return pieces


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return safe_text(redact(value))
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(
        f"session event data must be JSON values, got {type(value).__name__}"
    )


@dataclass(frozen=True)
class SessionEvent:
    """One event in the session stream. See docs/EVENTS_SESSION.md."""

    seq: int
    t: str
    session: str
    turn: int | None
    kind: str
    data: dict[str, Any]
    v: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "seq": self.seq,
            "t": self.t,
            "session": self.session,
            "turn": self.turn,
            "kind": self.kind,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


Subscriber = Callable[[SessionEvent], None]


@dataclass
class EventStream:
    """Ordered, thread-safe emitter for one session.

    Subscribers are called in order, on the emitting thread, while the
    stream's lock is held, so every subscriber sees events in ``seq`` order.
    A subscriber that raises is dropped from the stream (it must not take
    the session down) and the failure is reported as a ``notice``.
    """

    session: str
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    _subscribers: list[Subscriber] = field(default_factory=list)
    _seq: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock)
    # Monotonic time of the last event that was not a heartbeat; the
    # heartbeat only speaks during silence.
    last_activity: float = field(default_factory=time.monotonic)

    def subscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.append(subscriber)

    def emit(
        self, kind: str, data: dict[str, Any] | None = None, *, turn: int | None = None
    ) -> SessionEvent:
        if kind not in KINDS:
            reserved = " (reserved, not yet defined)" if kind in RESERVED_KINDS else ""
            raise UnknownEventKind(f"{kind!r} is not a session event kind{reserved}")
        payload = _clean(data or {})
        with self._lock:
            self._seq += 1
            if kind != "agent.heartbeat":
                self.last_activity = time.monotonic()
            stamp = self.clock().astimezone(timezone.utc)
            event = SessionEvent(
                seq=self._seq,
                t=stamp.strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{stamp.microsecond // 1000:03d}Z",
                session=self.session,
                turn=turn,
                kind=kind,
                data=payload,
            )
            failed: list[Subscriber] = []
            for subscriber in list(self._subscribers):
                try:
                    subscriber(event)
                except Exception:  # noqa: BLE001 -- a broken consumer must not stop the session
                    failed.append(subscriber)
            for subscriber in failed:
                self._subscribers.remove(subscriber)
        for subscriber in failed:
            name = getattr(subscriber, "__qualname__", type(subscriber).__name__)
            self.emit(
                "notice",
                {
                    "level": "warning",
                    "text": f"an event consumer ({name}) failed and was detached",
                },
                turn=turn,
            )
        return event

    def text(
        self,
        text: str,
        *,
        turn: int | None,
        reasoning: bool = False,
        channel: str = "answer",
        path: str | None = None,
    ) -> None:
        """Emit a complete text as one or more deltas within the size bound."""
        writer = self.writer(turn=turn, reasoning=reasoning, channel=channel, path=path)
        writer.feed(text)
        writer.close()

    def writer(
        self,
        *,
        turn: int | None,
        reasoning: bool = False,
        channel: str = "answer",
        path: str | None = None,
    ) -> TextWriter:
        """A writer for text that arrives in pieces (model streaming)."""
        return TextWriter(
            self, turn=turn, reasoning=reasoning, channel=channel, path=path
        )

    def error(
        self,
        message: str,
        *,
        hint: str,
        workspace: str,
        log: str | None = None,
        turn: int | None = None,
    ) -> None:
        """Emit ``error.surfaced``. ``hint`` must say what to do next."""
        if not hint.strip():
            raise ValueError(
                "error.surfaced needs a hint: the next action or the exact command"
            )
        self.emit(
            "error.surfaced",
            {"message": message, "hint": hint, "workspace": workspace, "log": log},
            turn=turn,
        )


class TextWriter:
    """Streams text deltas through a ``StreamingRedactor``.

    ``feed`` may emit nothing (the tail is held back); ``close`` emits the
    rest. Call ``close`` when the message ends, also on failure, or the
    held-back tail is lost.
    """

    def __init__(
        self,
        stream: EventStream,
        *,
        turn: int | None,
        reasoning: bool,
        channel: str,
        path: str | None,
    ) -> None:
        if channel not in {"answer", "artifact"}:
            raise ValueError(f"channel must be 'answer' or 'artifact', got {channel!r}")
        if channel == "artifact" and not path:
            raise ValueError("an artifact delta needs the path of the file")
        self._stream = stream
        self._turn = turn
        self._kind = "agent.reasoning.delta" if reasoning else "agent.text.delta"
        self._extra: dict[str, Any] = {} if reasoning else {"channel": channel}
        if path and not reasoning:
            self._extra["path"] = path
        self._redactor = StreamingRedactor()
        self.emitted = ""

    def _emit(self, text: str) -> None:
        for piece in split_text(text):
            self._stream.emit(
                self._kind, {"text": piece, **self._extra}, turn=self._turn
            )
            self.emitted += piece

    def feed(self, piece: str) -> None:
        ready = self._redactor.feed(piece)
        if ready:
            self._emit(ready)

    def close(self) -> None:
        rest = self._redactor.close()
        if rest:
            self._emit(rest)


def plan_event_data(plan: Any) -> dict[str, Any]:
    """``plan.proposed`` data from a Rooted plan (assumption, confidence, steps)."""
    return {
        "assumption": str(getattr(plan, "assumption", "")),
        "confidence": float(getattr(plan, "confidence", 0.0)),
        "steps": [
            {
                "n": n,
                "action": str(step.action),
                "target": step.expected_artifact or None,
            }
            for n, step in enumerate(getattr(plan, "steps", []), 1)
        ],
    }


class JsonlSink:
    """Writes each event as one JSON line (``--output-format stream-json``)."""

    def __init__(self, write: Callable[[str], Any]) -> None:
        self._write = write

    def __call__(self, event: SessionEvent) -> None:
        self._write(event.to_json() + "\n")


class Heartbeat:
    """Emits ``agent.heartbeat`` every ``interval`` seconds while active.

    Driven by a timer, not by the model, so a renderer has a sign of life
    while a slow local model has not produced its first token. It stays
    quiet while other events are arriving.

    >>> with Heartbeat(stream, turn=1, waiting_on="model"):
    ...     reply = provider.complete(...)
    """

    def __init__(
        self,
        stream: EventStream,
        *,
        turn: int | None,
        waiting_on: str,
        detail: str = "",
        interval: float = HEARTBEAT_SECONDS,
        cancel: threading.Event | None = None,
        connecting: Callable[[], str | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        pace: Callable[[float], bool] | None = None,
    ) -> None:
        self._stream = stream
        # The time source and the wait between beats. Production uses the real clock
        # and an Event wait; a test injects both so ticks are counted, not timed (B-071).
        self._clock = clock
        self._pace = (
            pace if pace is not None else (lambda seconds: self._stop.wait(seconds))
        )
        # The address being connected to, while a connect is in progress
        # (egress_ledger.watching_connections): "connecting to <address>"
        # says more than "waiting on model" while nothing answers (G-055).
        self._connecting = connecting
        # An interrupted turn's worker may wait on the model long after the
        # prompt is back; its heartbeat must not keep printing.
        self._cancel = cancel
        self._turn = turn
        self._waiting_on = waiting_on
        self._detail = detail
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def __enter__(self) -> Heartbeat:
        self._started = self._clock()
        self._thread = threading.Thread(
            target=self._run, name="ract-heartbeat", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)

    def _run(self) -> None:
        while not self._pace(self._interval):
            if self._cancel is not None and self._cancel.is_set():
                return
            if self._clock() - self._stream.last_activity < self._interval:
                continue  # something else spoke recently; no need for a sign of life
            elapsed = int((self._clock() - self._started) * 1000)
            address = self._connecting() if self._connecting is not None else None
            self._stream.emit(
                "agent.heartbeat",
                {
                    "waiting_on": "connection" if address else self._waiting_on,
                    "elapsed_ms": elapsed,
                    "detail": address or self._detail,
                },
                turn=self._turn,
            )
