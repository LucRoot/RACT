"""Null-sink event emitter helpers for the memory-discipline pipeline.

Seven event kinds land in ``src/ract/trace/events.py::EventKind`` in
module_09 (a load-bearing closed-vocabulary bump). Until that lands,
this module ships:

- an :class:`EventSink` protocol every emitter helper writes through,
- a :class:`NullEventSink` that records emissions in-memory (tests
  read the record; production wiring in module_09 swaps this for
  :class:`~ract.trace.writer.JsonlEventWriter`),
- seven emitter helpers keyed by the closed-vocabulary event kind
  string. Each helper takes the sink plus the payload dict and pushes
  the record onto the sink.

The emitter helpers do NOT depend on the closed EventKind vocabulary
type — they carry the event kind as a plain string so this module can
land without bumping the frozen ``Literal`` in ``ract.trace.events``.
Module_09 wires the seven kinds into the vocabulary and re-routes the
sink to the real event writer.

Reference: docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md §Signals items
1-2 (budget.declared, budget.exceeded) and §Signals items 3-7
(retrieval.requested, retrieval.satisfied, retrieval.cascaded,
retrieval.refused, probe.evaluated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ract.core.module_identity import _module_knot, register_module_knot


# Names of the seven event kinds this module emits. Kept as plain
# strings so they can land without bumping the closed EventKind
# Literal alias — module_09 does that in one commit alongside the
# real sink wiring.
BUDGET_DECLARED: str = "budget.declared"
BUDGET_EXCEEDED: str = "budget.exceeded"
RETRIEVAL_REQUESTED: str = "retrieval.requested"
RETRIEVAL_SATISFIED: str = "retrieval.satisfied"
RETRIEVAL_CASCADED: str = "retrieval.cascaded"
RETRIEVAL_REFUSED: str = "retrieval.refused"
PROBE_EVALUATED: str = "probe.evaluated"


MEMORY_EVENT_KINDS: frozenset[str] = frozenset(
    {
        BUDGET_DECLARED,
        BUDGET_EXCEEDED,
        RETRIEVAL_REQUESTED,
        RETRIEVAL_SATISFIED,
        RETRIEVAL_CASCADED,
        RETRIEVAL_REFUSED,
        PROBE_EVALUATED,
    }
)


class EventSink(Protocol):
    """Protocol for the event sink an emitter helper writes through.

    Module_09 wires :class:`~ract.trace.writer.JsonlEventWriter` under
    this protocol; until then :class:`NullEventSink` is the default.
    """

    def emit(self, kind: str, payload: dict[str, Any]) -> None: ...


@dataclass
class NullEventSink:
    """In-memory sink that records emissions for inspection.

    Records land in :attr:`records` as ``(kind, payload)`` tuples in
    emission order. Tests read the list; production wiring swaps this
    for the real writer in module_09.
    """

    records: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        """Record ``(kind, payload)`` on the sink."""
        if kind not in MEMORY_EVENT_KINDS:
            raise ValueError(
                f"NullEventSink.emit: unknown event kind {kind!r}; "
                f"legal: {sorted(MEMORY_EVENT_KINDS)!r}"
            )
        # Copy the payload so a caller who mutates the dict after
        # emission cannot retroactively change what the sink records.
        self.records.append((kind, dict(payload)))


def _emit(sink: EventSink, kind: str, payload: dict[str, Any]) -> None:
    """Shared entry point every helper below delegates through."""
    if kind not in MEMORY_EVENT_KINDS:
        raise ValueError(
            f"emit: unknown event kind {kind!r}; legal: {sorted(MEMORY_EVENT_KINDS)!r}"
        )
    sink.emit(kind, dict(payload))


def emit_budget_declared(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``budget.declared`` — declared budget for one invocation.

    Payload keys (module_09 formalises the schema in
    ``docs/EVENTS.md``): ``function``, ``declaration`` (dataclass
    ``asdict``), ``narrowing_log`` (list of :class:`BudgetNarrowing`
    ``asdict`` values), ``source`` (composition | runtime | cli |
    default).
    """
    _emit(sink, BUDGET_DECLARED, payload)


def emit_budget_exceeded(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``budget.exceeded`` — pre-model refuse on ceiling violation.

    Payload keys: ``function``, ``section_name``, ``delta``,
    ``boundary`` (``input_max`` or ``hard_ceiling``).
    """
    _emit(sink, BUDGET_EXCEEDED, payload)


def emit_retrieval_requested(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``retrieval.requested`` — a retrieve call was issued."""
    _emit(sink, RETRIEVAL_REQUESTED, payload)


def emit_retrieval_satisfied(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``retrieval.satisfied`` — a retrieve call returned a bundle."""
    _emit(sink, RETRIEVAL_SATISFIED, payload)


def emit_retrieval_cascaded(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``retrieval.cascaded`` — the retrieval cascade downgraded a level."""
    _emit(sink, RETRIEVAL_CASCADED, payload)


def emit_retrieval_refused(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``retrieval.refused`` — the retrieval cascade exhausted every level."""
    _emit(sink, RETRIEVAL_REFUSED, payload)


def emit_probe_evaluated(sink: EventSink, payload: dict[str, Any]) -> None:
    """Emit ``probe.evaluated`` — a quality probe ran and returned a score."""
    _emit(sink, PROBE_EVALUATED, payload)


__all__ = [
    "BUDGET_DECLARED",
    "BUDGET_EXCEEDED",
    "EventSink",
    "MEMORY_EVENT_KINDS",
    "NullEventSink",
    "PROBE_EVALUATED",
    "RETRIEVAL_CASCADED",
    "RETRIEVAL_REFUSED",
    "RETRIEVAL_REQUESTED",
    "RETRIEVAL_SATISFIED",
    "emit_budget_declared",
    "emit_budget_exceeded",
    "emit_probe_evaluated",
    "emit_retrieval_cascaded",
    "emit_retrieval_refused",
    "emit_retrieval_requested",
    "emit_retrieval_satisfied",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
