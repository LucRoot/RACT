"""Event-trace substrate — hash-chained JSONL log + OTLP mirror.

SUBSTRATE spec §6 (Substrate Layer 5: The Trace is the Product) and §11
signals 9, 10, 11. This package is the substrate the ``RunReporter``
now projects over.
"""

from __future__ import annotations

from ract.trace.events import (
    ChainBrokenError,
    Event,
    EventChain,
    EventKind,
    LEGAL_EVENT_KINDS,
    canonical_payload_bytes,
    hash_event,
    new_event_id,
)
from ract.trace.otel import OtlpExporter, event_to_span_attributes, install_otlp_exporter
from ract.trace.writer import EventReader, JsonlEventWriter, RedactionProfile

__all__ = [
    "ChainBrokenError",
    "Event",
    "EventChain",
    "EventKind",
    "EventReader",
    "JsonlEventWriter",
    "LEGAL_EVENT_KINDS",
    "OtlpExporter",
    "RedactionProfile",
    "canonical_payload_bytes",
    "event_to_span_attributes",
    "hash_event",
    "install_otlp_exporter",
    "new_event_id",
]


# RACT 0.4.0
