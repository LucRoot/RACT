"""Module-level event sink registry.

Every emit site (IntentCompiler, StepTransaction, sandbox, providers,
handshake registry, predicates, provenance, assumption registry) calls
``emit(kind, payload, ...)`` from this module. A run's
``JsonlEventWriter`` registers itself via ``set_writer``; without a
registered writer, the sink is a null drop (so unit tests that construct
an ``IntentCompiler`` without a run scope still work).

SUBSTRATE §6.4. The single-writer-per-run contract is enforced by the
sink: ``set_writer`` refuses to overwrite an existing writer unless
``force=True``; the loop's finalizer calls ``clear_writer`` at run
close.
"""

from __future__ import annotations

from typing import Any, Callable

from ract.trace.events import EventKind


# The public sink signature: (kind, payload, step_id, parent_id, timestamp_ns)
EventSink = Callable[..., Any]


def _null_sink(
    kind: EventKind,
    payload: dict[str, Any],
    *,
    step_id: bytes | None = None,
    parent_id: bytes | None = None,
    timestamp_ns: int | None = None,
) -> None:
    """Drop the event. Used when no writer is registered."""
    del kind, payload, step_id, parent_id, timestamp_ns


_sink: EventSink = _null_sink
_writer: Any = None


def emit(
    kind: EventKind,
    payload: dict[str, Any],
    *,
    step_id: bytes | None = None,
    parent_id: bytes | None = None,
    timestamp_ns: int | None = None,
) -> Any:
    """Publish one event to the active sink.

    Returns whatever the sink returns (usually the persisted ``Event``
    value from ``JsonlEventWriter.emit``, or ``None`` for the null
    sink).
    """
    return _sink(
        kind,
        payload,
        step_id=step_id,
        parent_id=parent_id,
        timestamp_ns=timestamp_ns,
    )


def set_writer(writer: Any, *, force: bool = False) -> None:
    """Register ``writer`` as the current run's event writer.

    ``writer`` must expose an ``emit(kind, payload, *, step_id, parent_id,
    timestamp_ns) -> Event`` method (``JsonlEventWriter`` satisfies this).
    Refuses to replace an existing writer unless ``force=True``.
    """
    global _sink, _writer
    if _writer is not None and not force:
        raise RuntimeError(
            "an event writer is already registered; call clear_writer() "
            "first or pass force=True"
        )
    _writer = writer
    _sink = writer.emit  # bound method


def clear_writer() -> None:
    """Drop the current writer and revert to the null sink."""
    global _sink, _writer
    _writer = None
    _sink = _null_sink


def current_writer() -> Any:
    """Return the currently registered writer (or ``None``)."""
    return _writer


def has_writer() -> bool:
    """Convenience predicate — true when a live writer is registered."""
    return _writer is not None


__all__ = [
    "clear_writer",
    "current_writer",
    "emit",
    "has_writer",
    "set_writer",
]


# RACT 0.4.0
